"""PNCP (Portal Nacional de Contratações Públicas): contratações, itens, resultados e contratos.

APIs públicas, sem chave:
- consulta: https://pncp.gov.br/api/consulta/v1 (contratações por UF, contratos)
- pncp:     https://pncp.gov.br/api/pncp/v1 (itens e resultados de cada contratação)
"""

from __future__ import annotations

import gzip
import json
from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path

from cgu import cnpj as cnpj_mod
from cgu.ingest.http import ApiClient

CONSULTA = "https://pncp.gov.br/api/consulta/v1"
PNCP = "https://pncp.gov.br/api/pncp/v1"

# Códigos de modalidade do PNCP (Lei 14.133) -> modalidade canônica
MODALIDADES = {
    1: "outra",  # leilão eletrônico
    2: "outra",  # diálogo competitivo
    3: "outra",  # concurso
    4: "concorrencia",  # concorrência eletrônica
    5: "concorrencia",  # concorrência presencial
    6: "pregao",  # pregão eletrônico
    7: "pregao",  # pregão presencial
    8: "dispensa",
    9: "inexigibilidade",
    10: "outra",  # manifestação de interesse
    11: "outra",  # pré-qualificação
    12: "outra",  # credenciamento
    13: "outra",  # leilão presencial
}
ESFERAS = {"F": "federal", "E": "estadual", "M": "municipal", "D": "estadual"}


def month_windows(start: date, end: date) -> Iterator[tuple[date, date]]:
    cur = date(start.year, start.month, 1)
    while cur <= end:
        nxt = date(cur.year + (cur.month == 12), cur.month % 12 + 1, 1)
        yield max(cur, start), min(nxt - timedelta(days=1), end)
        cur = nxt


def _d(value: str | None) -> str | None:
    return value[:10] if value else None


# ----------------------------------------------------------------- parsers (puros)
def parse_compra(rec: dict) -> dict:
    org, un = rec.get("orgaoEntidade") or {}, rec.get("unidadeOrgao") or {}
    return {
        "compra_id": rec["numeroControlePNCP"],
        "orgao_cnpj": org.get("cnpj"),
        "orgao_nome": org.get("razaoSocial"),
        "esfera": ESFERAS.get(org.get("esferaId"), "municipal"),
        "unidade_codigo": un.get("codigoUnidade"),
        "unidade_nome": un.get("nomeUnidade"),
        "uf": un.get("ufSigla"),
        "municipio": un.get("municipioNome"),
        "modalidade_id": rec.get("modalidadeId"),
        "modalidade": MODALIDADES.get(rec.get("modalidadeId"), "outra"),
        "numero_compra": rec.get("numeroCompra"),
        "ano": rec.get("anoCompra"),
        "sequencial": rec.get("sequencialCompra"),
        "objeto": rec.get("objetoCompra"),
        "data_publicacao": _d(rec.get("dataPublicacaoPncp")),
        "valor_estimado": rec.get("valorTotalEstimado"),
        "valor_homologado": rec.get("valorTotalHomologado"),
    }


def parse_item(compra_id: str, rec: dict) -> dict:
    return {
        "compra_id": compra_id,
        "numero_item": rec.get("numeroItem"),
        "descricao": rec.get("descricao"),
        "material_servico": rec.get("materialOuServico"),
        "item_code": (str(rec["catalogoCodigoItem"]) if rec.get("catalogoCodigoItem") else None),
        "unidade": rec.get("unidadeMedida"),
        "quantidade": rec.get("quantidade"),
        "valor_unitario_estimado": rec.get("valorUnitarioEstimado"),
        "tem_resultado": bool(rec.get("temResultado")),
    }


def parse_resultado(compra_id: str, rec: dict) -> dict | None:
    if rec.get("tipoPessoa") != "PJ" or rec.get("dataCancelamento"):
        return None
    doc = cnpj_mod.normalize(rec.get("niFornecedor"))
    if not doc:
        return None
    return {
        "compra_id": compra_id,
        "numero_item": rec.get("numeroItem"),
        "cnpj": doc,
        "nome": rec.get("nomeRazaoSocialFornecedor"),
        "porte": rec.get("porteFornecedorNome"),
        "quantidade": rec.get("quantidadeHomologada"),
        "valor_unitario": rec.get("valorUnitarioHomologado"),
        "valor_total": rec.get("valorTotalHomologado"),
        "data_resultado": _d(rec.get("dataResultado")),
    }


def parse_contrato(rec: dict) -> dict | None:
    if rec.get("tipoPessoa") != "PJ":
        return None
    doc = cnpj_mod.normalize(rec.get("niFornecedor"))
    if not doc:
        return None
    org, un = rec.get("orgaoEntidade") or {}, rec.get("unidadeOrgao") or {}
    return {
        "contrato_id": rec["numeroControlePNCP"],
        "compra_id": rec.get("numeroControlePncpCompra"),
        "orgao_cnpj": org.get("cnpj"),
        "orgao_nome": org.get("razaoSocial"),
        "esfera": ESFERAS.get(org.get("esferaId"), "municipal"),
        "unidade_codigo": un.get("codigoUnidade"),
        "unidade_nome": un.get("nomeUnidade"),
        "uf": un.get("ufSigla"),
        "municipio": un.get("municipioNome"),
        "cnpj": doc,
        "nome_fornecedor": rec.get("nomeRazaoSocialFornecedor"),
        "objeto": rec.get("objetoContrato"),
        "categoria": (rec.get("categoriaProcesso") or {}).get("nome"),
        "valor_inicial": rec.get("valorInicial"),
        "valor_global": rec.get("valorGlobal"),
        "valor_acumulado": rec.get("valorAcumulado"),
        "data_assinatura": rec.get("dataAssinatura"),
        "data_publicacao": _d(rec.get("dataPublicacaoPncp")),
        "vigencia_inicio": rec.get("dataVigenciaInicio"),
        "vigencia_fim": rec.get("dataVigenciaFim"),
    }


# ----------------------------------------------------------------- coleta
def fetch_compras(client: ApiClient, uf: str, start: date, end: date) -> list[dict]:
    out = []
    for d1, d2 in month_windows(start, end):
        for mod in MODALIDADES:
            page = 1
            while True:
                data = client.get_json(
                    "contratacoes/publicacao",
                    {
                        "dataInicial": d1.strftime("%Y%m%d"),
                        "dataFinal": d2.strftime("%Y%m%d"),
                        "codigoModalidadeContratacao": mod,
                        "uf": uf,
                        "pagina": page,
                        "tamanhoPagina": 50,
                    },
                )
                if not data or not data.get("data"):
                    break
                out += [parse_compra(r) for r in data["data"]]
                if not data.get("paginasRestantes"):
                    break
                page += 1
    return out


def fetch_itens(client: ApiClient, compra: dict) -> list[dict]:
    out, page = [], 1
    path = f"orgaos/{compra['orgao_cnpj']}/compras/{compra['ano']}/{compra['sequencial']}/itens"
    while True:
        data = client.get_json(path, {"pagina": page, "tamanhoPagina": 50})
        if not data:
            break
        out += [parse_item(compra["compra_id"], r) for r in data]
        if len(data) < 50:
            break
        page += 1
    return out


def fetch_resultados(client: ApiClient, compra: dict, numero_item: int) -> list[dict]:
    path = (
        f"orgaos/{compra['orgao_cnpj']}/compras/{compra['ano']}/{compra['sequencial']}"
        f"/itens/{numero_item}/resultados"
    )
    data = client.get_json(path) or []
    return [r for r in (parse_resultado(compra["compra_id"], x) for x in data) if r]


def fetch_contratos(
    client: ApiClient, uf: str, start: date, end: date, checkpoint_dir: Path
) -> list[dict]:
    """A API de contratos não filtra por UF: pagina o país dia a dia e guarda só a UF.

    Cada dia filtrado vira um checkpoint (o volume nacional não é mantido em disco).
    """
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    out, day = [], start
    while day <= end:
        cp = checkpoint_dir / f"{uf}_{day:%Y%m%d}.json.gz"
        if cp.exists():
            with gzip.open(cp, "rt", encoding="utf-8") as f:
                out += json.load(f)
        else:
            rows, page = [], 1
            while True:
                data = client.get_json(
                    "contratos",
                    {
                        "dataInicial": day.strftime("%Y%m%d"),
                        "dataFinal": day.strftime("%Y%m%d"),
                        "pagina": page,
                        "tamanhoPagina": 500,
                    },
                    cache=False,
                )
                if not data or not data.get("data"):
                    break
                rows += [
                    r for r in (parse_contrato(x) for x in data["data"]) if r and r["uf"] == uf
                ]
                if not data.get("paginasRestantes"):
                    break
                page += 1
            with gzip.open(cp, "wt", encoding="utf-8") as f:
                json.dump(rows, f, ensure_ascii=False)
            out += rows
        day += timedelta(days=1)
    return out
