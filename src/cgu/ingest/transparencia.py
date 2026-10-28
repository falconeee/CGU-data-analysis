"""Portal da Transparência (API de dados, requer CGU_API_KEY no header `chave-api-dados`).

Usado para a lista de **participantes** das licitações federais (o PNCP só publica os
vencedores) e para o CEIS/CNEP. Os downloads em lote do Portal (ZIP) recusaram acesso
automatizado nos testes, por isso tudo vem pela API.
"""

from __future__ import annotations

from cgu import cnpj as cnpj_mod
from cgu.config import Config
from cgu.ingest.http import ApiClient

BASE = "https://api.portaldatransparencia.gov.br/api-de-dados"


def client(cfg: Config) -> ApiClient:
    if not cfg.api_key:
        raise RuntimeError(
            "CGU_API_KEY não definida (.env). Necessária para o Portal da Transparência."
        )
    return ApiClient(
        BASE,
        cfg.path("raw_dir") / "cache" / "portal",
        cfg["real"]["portal_rate_per_min"],
        {"chave-api-dados": cfg.api_key},
    )


def parse_participante(licitacao_id: str, rec: dict) -> dict | None:
    doc = cnpj_mod.normalize(rec.get("cpfCnpj"))
    if not doc:  # pessoas físicas ficam de fora
        return None
    return {"licitacao_id": licitacao_id, "cnpj": doc, "nome": rec.get("nome")}


def fetch_participantes(
    c: ApiClient, licitacao_id: str, ug: str, numero: str, codigo_modalidade: int
) -> list[dict]:
    out, page = [], 1
    while True:
        data = c.get_json(
            "licitacoes/participantes",
            {
                "codigoUG": ug,
                "numero": numero,
                "codigoModalidade": codigo_modalidade,
                "pagina": page,
            },
        )
        if not data:
            break
        out += [p for p in (parse_participante(licitacao_id, r) for r in data) if p]
        page += 1
    return out
