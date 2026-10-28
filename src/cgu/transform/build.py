"""Modo real: tabelas de staging (data/raw/staging) -> modelo canônico.

Decisões de mapeamento:
- Órgão = órgão + unidade do PNCP (agency_id = "<cnpj do órgão>-<código da unidade>").
- Contrato = contrato publicado no PNCP; quando a contratação tem resultado mas nenhum
  contrato publicado (comum em dispensas pagas por empenho), cria-se um contrato derivado
  por (contratação, fornecedor), somando os itens homologados.
- Licitantes = participantes do Portal da Transparência (só licitações federais) + vencedores.
- Itens = itens com resultado homologado (preço efetivamente contratado).
- Aditivos não são coletados (endpoint por contrato); n_amendments = 0 e o valor final é o
  maior entre valor inicial, global e acumulado.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from cgu import schema
from cgu.config import Config

STAGING = {
    "pncp_compra": [
        "compra_id",
        "orgao_cnpj",
        "orgao_nome",
        "esfera",
        "unidade_codigo",
        "unidade_nome",
        "uf",
        "municipio",
        "modalidade_id",
        "modalidade",
        "numero_compra",
        "ano",
        "sequencial",
        "objeto",
        "data_publicacao",
        "valor_estimado",
        "valor_homologado",
    ],
    "pncp_item": [
        "compra_id",
        "numero_item",
        "descricao",
        "material_servico",
        "item_code",
        "unidade",
        "quantidade",
        "valor_unitario_estimado",
        "tem_resultado",
    ],
    "pncp_resultado": [
        "compra_id",
        "numero_item",
        "cnpj",
        "nome",
        "porte",
        "quantidade",
        "valor_unitario",
        "valor_total",
        "data_resultado",
    ],
    "pncp_contrato": [
        "contrato_id",
        "compra_id",
        "orgao_cnpj",
        "orgao_nome",
        "esfera",
        "unidade_codigo",
        "unidade_nome",
        "uf",
        "municipio",
        "cnpj",
        "nome_fornecedor",
        "objeto",
        "categoria",
        "valor_inicial",
        "valor_global",
        "valor_acumulado",
        "data_assinatura",
        "data_publicacao",
        "vigencia_inicio",
        "vigencia_fim",
    ],
    "portal_participante": ["licitacao_id", "cnpj", "nome"],
    "sancao": ["cnpj", "source", "start_date", "end_date", "sanction_type", "authority"],
    "receita_supplier": ["cnpj", "cnpj_base", "name", "opened_at", "uf", "size"],
    "receita_partner": ["cnpj_base", "partner_name", "partner_doc", "joined_at"],
    "ref_price": ["item_code", "uf", "year", "median", "q1", "q3", "n_obs"],
}


def load_staging(staging: Path) -> dict[str, pd.DataFrame]:
    out = {}
    for name, cols in STAGING.items():
        f = staging / f"{name}.parquet"
        df = pd.read_parquet(f) if f.exists() else pd.DataFrame(columns=cols)
        out[name] = df.reindex(columns=cols) if df.empty else df
    return out


def _agency_rows(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["agency_id", "name", "sphere", "uf", "municipality"])
    same = df["unidade_nome"].fillna("").str.upper() == df["orgao_nome"].fillna("").str.upper()
    return pd.DataFrame(
        {
            "agency_id": df["orgao_cnpj"].astype(str) + "-" + df["unidade_codigo"].astype(str),
            "name": np.where(
                same | df["unidade_nome"].isna(),
                df["orgao_nome"],
                df["orgao_nome"].fillna("") + " — " + df["unidade_nome"].fillna(""),
            ),
            "sphere": df["esfera"],
            "uf": df["uf"],
            "municipality": df["municipio"],
        }
    )


def _is_engineering(name: str) -> bool:
    n = (name or "").lower()
    return "engenharia" in n or "obra" in n


def build_tables(st: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    compras, itens, res = st["pncp_compra"], st["pncp_item"], st["pncp_resultado"]
    contratos, part = st["pncp_contrato"], st["portal_participante"]

    agency = pd.concat([_agency_rows(compras), _agency_rows(contratos)]).drop_duplicates(
        "agency_id"
    )

    # Categoria da contratação: a do contrato, senão material/serviço pela maioria dos itens.
    cat_by_compra = (
        contratos.dropna(subset=["compra_id", "categoria"])
        .groupby("compra_id")["categoria"]
        .first()
    )
    kind = itens.groupby("compra_id")["material_servico"].agg(
        lambda s: s.mode().iloc[0] if not s.mode().empty else None
    )
    kind = kind.map({"M": "Compras", "S": "Serviços"})
    tender = pd.DataFrame(
        {
            "tender_id": compras["compra_id"],
            "agency_id": compras["orgao_cnpj"].astype(str)
            + "-"
            + compras["unidade_codigo"].astype(str),
            "modality": compras["modalidade"],
            "category": compras["compra_id"]
            .map(cat_by_compra)
            .astype(object)
            .fillna(compras["compra_id"].map(kind)),
            "object": compras["objeto"],
            "published_at": pd.to_datetime(compras["data_publicacao"]),
            "estimated_value": compras["valor_estimado"],
        }
    ).drop_duplicates("tender_id")
    t_idx = tender.set_index("tender_id")

    # Contratos publicados
    c = contratos.drop_duplicates("contrato_id")
    linked = c["compra_id"].isin(t_idx.index)
    published = pd.DataFrame(
        {
            "contract_id": c["contrato_id"],
            "tender_id": c["compra_id"].where(linked),
            "agency_id": c["orgao_cnpj"].astype(str) + "-" + c["unidade_codigo"].astype(str),
            "cnpj": c["cnpj"],
            "modality": c["compra_id"].map(t_idx["modality"]).fillna("outra"),
            "category": c["categoria"],
            "object": c["objeto"],
            "signed_at": pd.to_datetime(c["data_assinatura"], errors="coerce"),
            "published_at": pd.to_datetime(c["data_publicacao"], errors="coerce"),
            "start_date": pd.to_datetime(c["vigencia_inicio"], errors="coerce"),
            "end_date": pd.to_datetime(c["vigencia_fim"], errors="coerce"),
            "value_initial": c["valor_inicial"].fillna(0).clip(lower=0),
            "value_final": c[["valor_inicial", "valor_global", "valor_acumulado"]]
            .max(axis=1)
            .fillna(0)
            .clip(lower=0),
            "n_amendments": 0,
        }
    )

    # Contratos derivados de resultados sem contrato publicado
    have = set(zip(published["tender_id"], published["cnpj"], strict=True))
    r = res[res["compra_id"].isin(t_idx.index)].copy()
    r["key"] = list(zip(r["compra_id"], r["cnpj"], strict=True))
    derived_src = r[~r["key"].isin(have)]
    derived = derived_src.groupby(["compra_id", "cnpj"], as_index=False).agg(
        value=("valor_total", "sum"), signed=("data_resultado", "max")
    )
    derived = pd.DataFrame(
        {
            "contract_id": derived["compra_id"] + "/" + derived["cnpj"],
            "tender_id": derived["compra_id"],
            "agency_id": derived["compra_id"].map(t_idx["agency_id"]),
            "cnpj": derived["cnpj"],
            "modality": derived["compra_id"].map(t_idx["modality"]),
            "category": derived["compra_id"].map(t_idx["category"]),
            "object": derived["compra_id"].map(t_idx["object"]),
            "signed_at": pd.to_datetime(derived["signed"], errors="coerce").fillna(
                derived["compra_id"].map(t_idx["published_at"])
            ),
            "published_at": pd.NaT,
            "start_date": pd.NaT,
            "end_date": pd.NaT,
            "value_initial": derived["value"].fillna(0).clip(lower=0),
            "value_final": derived["value"].fillna(0).clip(lower=0),
            "n_amendments": 0,
        }
    )
    contract = pd.concat([published, derived], ignore_index=True)
    contract = contract.dropna(subset=["signed_at", "agency_id", "cnpj"])

    # Licitantes: participantes + vencedores
    winners = (
        contract.dropna(subset=["tender_id"])
        .groupby(["tender_id", "cnpj"], as_index=False)["value_initial"]
        .sum()
    )
    p = part.rename(columns={"licitacao_id": "tender_id"})[["tender_id", "cnpj"]]
    p = p[p["tender_id"].isin(t_idx.index)]
    bidder = pd.concat([p, winners[["tender_id", "cnpj"]]]).drop_duplicates()
    bidder = bidder.merge(
        winners.rename(columns={"value_initial": "bid_value"}), on=["tender_id", "cnpj"], how="left"
    )
    bidder["is_winner"] = bidder["bid_value"].notna()

    # Itens com preço homologado, ligados ao contrato do fornecedor
    contract_of = {
        (t, d): cid
        for cid, t, d in contract[["contract_id", "tender_id", "cnpj"]].itertuples(index=False)
    }
    it = r.merge(
        itens[["compra_id", "numero_item", "descricao", "item_code", "unidade"]],
        on=["compra_id", "numero_item"],
        how="left",
    )
    item = pd.DataFrame(
        {
            "item_id": it["compra_id"] + "#" + it["numero_item"].astype(str) + "#" + it["cnpj"],
            "tender_id": it["compra_id"],
            "contract_id": [
                contract_of.get(k) for k in zip(it["compra_id"], it["cnpj"], strict=True)
            ],
            "item_code": it["item_code"],
            "description": it["descricao"],
            "unit": it["unidade"],
            "quantity": it["quantidade"].fillna(0),
            "unit_price": it["valor_unitario"].fillna(0),
            "uf": it["compra_id"].map(compras.set_index("compra_id")["uf"].to_dict()),
            "date": pd.to_datetime(it["data_resultado"], errors="coerce").fillna(
                it["compra_id"].map(t_idx["published_at"])
            ),
        }
    ).drop_duplicates("item_id")

    # Fornecedores: Receita quando disponível, senão nome das próprias contratações
    docs = pd.Index(pd.concat([contract["cnpj"], bidder["cnpj"]]).unique())
    names = (
        pd.concat(
            [
                contratos[["cnpj", "nome_fornecedor"]].set_axis(["cnpj", "name"], axis=1),
                res[["cnpj", "nome"]].set_axis(["cnpj", "name"], axis=1),
                part[["cnpj", "nome"]].set_axis(["cnpj", "name"], axis=1),
            ]
        )
        .dropna()
        .drop_duplicates("cnpj")
        .set_index("cnpj")["name"]
    )
    rec = st["receita_supplier"].drop_duplicates("cnpj").set_index("cnpj")
    supplier = pd.DataFrame({"cnpj": docs})
    supplier["cnpj_base"] = supplier["cnpj"].str[:8]
    supplier["name"] = (
        supplier["cnpj"]
        .map(rec["name"])
        .astype(object)
        .fillna(supplier["cnpj"].map(names))
        .fillna("(sem nome)")
    )
    supplier["opened_at"] = pd.to_datetime(supplier["cnpj"].map(rec["opened_at"]))
    supplier["uf"] = supplier["cnpj"].map(rec["uf"])
    supplier["size"] = supplier["cnpj"].map(rec["size"])

    partner = st["receita_partner"]
    partner = partner[partner["cnpj_base"].isin(set(supplier["cnpj_base"]))]

    categories = pd.Series(pd.concat([tender["category"], contract["category"]]).dropna().unique())
    category = pd.DataFrame(
        {
            "category_id": categories,
            "name": categories,
            "engineering": categories.map(_is_engineering),
        }
    )

    sanction = st["sancao"].drop_duplicates()
    sanction = sanction.assign(
        start_date=pd.to_datetime(sanction["start_date"]),
        end_date=pd.to_datetime(sanction["end_date"]),
    )
    ref = st["ref_price"].drop_duplicates(["item_code", "uf", "year"])

    return {
        "agency": agency,
        "category": category,
        "supplier": supplier,
        "partner": partner,
        "tender": tender,
        "bidder": bidder,
        "contract": contract,
        "item": item,
        "ref_price": ref,
        "sanction": sanction,
    }


def build(cfg: Config) -> dict[str, pd.DataFrame]:
    staging = cfg.path("raw_dir") / "staging"
    if not (staging / "pncp_compra.parquet").exists():
        raise FileNotFoundError(f"Sem dados em {staging}. Rode `cgu ingest` antes.")
    return schema.validate(build_tables(load_staging(staging)))
