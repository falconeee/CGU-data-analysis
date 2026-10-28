"""Parsers e transform do modo real, com respostas de API gravadas (sem rede)."""

import zipfile

import pandas as pd

from cgu import schema
from cgu.ingest import cnpj_receita, pncp, precos, sancoes, transparencia
from cgu.ingest.run import portal_numero
from cgu.transform.build import build_tables, load_staging
from conftest import fixture


def test_parse_compra_item_resultado():
    compra = pncp.parse_compra(fixture("pncp_contratacoes.json")["data"][0])
    assert compra["compra_id"] == "27080530000143-1-000097/2025"
    assert compra["modalidade"] == "pregao" and compra["esfera"] == "estadual"
    assert compra["uf"] == "ES" and compra["data_publicacao"] == "2025-03-10"
    items = [pncp.parse_item(compra["compra_id"], r) for r in fixture("pncp_itens.json")]
    assert items[0]["numero_item"] == 1 and items[0]["material_servico"] == "M"
    res = pncp.parse_resultado(compra["compra_id"], fixture("pncp_resultados.json")[0])
    assert res["cnpj"] == "31804909000126" and res["valor_unitario"] == 11.6


def test_parse_contrato():
    c = pncp.parse_contrato(fixture("pncp_contratos.json")["data"][0])
    assert c["uf"] == "PB" and c["cnpj"] == "53796566000138"
    assert c["compra_id"] == "08924078000104-1-000013/2025"
    assert pncp.parse_contrato({"tipoPessoa": "PF", "niFornecedor": "12345678901"}) is None


def test_parse_sancoes_only_companies():
    assert sancoes.parse_sancao("CEIS", fixture("ceis.json")[0]) is None  # pessoa física
    s = sancoes.parse_sancao("CNEP", fixture("cnep.json")[0])
    assert s["cnpj"] == "29118884000165"
    assert s["start_date"] == "2025-07-24" and s["end_date"] == "2030-07-23"


def test_parse_participante_and_numero():
    p = transparencia.parse_participante("L1", {"cpfCnpj": "34.307.295/0001-65", "nome": "X"})
    assert p == {"licitacao_id": "L1", "cnpj": "34307295000165", "nome": "X"}
    assert transparencia.parse_participante("L1", {"cpfCnpj": "***.111.222-**"}) is None
    assert portal_numero("90051", 2024) == "900512024"
    assert portal_numero("51", 2024) == "000512024"
    assert portal_numero("ABC", 2024) is None


def test_month_windows():
    from datetime import date

    w = list(pncp.month_windows(date(2024, 11, 15), date(2025, 1, 10)))
    assert w == [
        (date(2024, 11, 15), date(2024, 11, 30)),
        (date(2024, 12, 1), date(2024, 12, 31)),
        (date(2025, 1, 1), date(2025, 1, 10)),
    ]


def test_precos_summarize():
    rows = fixture("precos_servico.json")["resultado"]
    obs = pd.DataFrame(
        [
            {
                "item_code": str(r["codigoItemCatalogo"]),
                "uf": r["estado"],
                "date": r["dataCompra"],
                "price": r["precoUnitario"],
            }
            for r in rows
        ]
    )
    ref = precos.summarize(obs)
    assert list(ref.columns) == ["item_code", "uf", "year", "median", "q1", "q3", "n_obs"]
    assert ref["n_obs"].sum() == len(rows)


def test_receita_filter_zip(tmp_path):
    zpath = tmp_path / "Socios0.zip"
    lines = [
        '"11111111";"2";"FULANO";"***123456**";"49";"20200101";"";"";"";"";"4"',
        '"22222222";"2";"OUTRO";"***654321**";"49";"20190101";"";"";"";"";"5"',
    ]
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("K3241.SOCIOCSV", "\n".join(lines).encode("latin-1"))
    df = cnpj_receita.filter_zip(zpath, "Socios", {"11111111"})
    assert df.to_dict("records") == [
        {
            "cnpj_basico": "11111111",
            "nome_socio": "FULANO",
            "cpf_cnpj_socio": "***123456**",
            "data_entrada_sociedade": "20200101",
        }
    ]


def test_build_from_fixture_staging(tmp_path):
    staging = tmp_path / "staging"
    staging.mkdir()
    compra = pncp.parse_compra(fixture("pncp_contratacoes.json")["data"][0])
    itens = [pncp.parse_item(compra["compra_id"], r) for r in fixture("pncp_itens.json")]
    res = [pncp.parse_resultado(compra["compra_id"], r) for r in fixture("pncp_resultados.json")]
    pd.DataFrame([compra]).to_parquet(staging / "pncp_compra.parquet")
    pd.DataFrame(itens).to_parquet(staging / "pncp_item.parquet")
    pd.DataFrame(res).to_parquet(staging / "pncp_resultado.parquet")
    pd.DataFrame(
        [{"licitacao_id": compra["compra_id"], "cnpj": "34307295000165", "nome": "CONCORRENTE"}]
    ).to_parquet(staging / "portal_participante.parquet")

    tables = schema.validate(build_tables(load_staging(staging)))
    contract = tables["contract"].iloc[0]
    # sem contrato publicado: contrato derivado do resultado homologado
    assert contract["contract_id"] == f"{compra['compra_id']}/31804909000126"
    assert contract["value_initial"] == 371.2 and contract["modality"] == "pregao"
    bidders = tables["bidder"].set_index("cnpj")
    assert bidders.loc["31804909000126", "is_winner"]
    assert not bidders.loc["34307295000165", "is_winner"]
    assert tables["item"]["unit_price"].tolist() == [11.6]
    assert tables["agency"]["sphere"].tolist() == ["estadual"]
