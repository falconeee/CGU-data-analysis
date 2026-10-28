"""CEIS e CNEP (empresas sancionadas) via API do Portal da Transparência."""

from __future__ import annotations

from datetime import datetime

from cgu import cnpj as cnpj_mod
from cgu.ingest.http import ApiClient


def _date(value: str | None) -> str | None:
    if not value or value == "Sem informação":
        return None
    try:
        return datetime.strptime(value, "%d/%m/%Y").date().isoformat()
    except ValueError:
        return None


def parse_sancao(source: str, rec: dict) -> dict | None:
    pessoa = rec.get("pessoa") or {}
    if pessoa.get("cpfFormatado"):  # pessoa física
        return None
    doc = cnpj_mod.normalize(
        pessoa.get("cnpjFormatado") or (rec.get("sancionado") or {}).get("codigoFormatado")
    )
    if not doc:  # só pessoas jurídicas
        return None
    return {
        "cnpj": doc,
        "source": source,
        "start_date": _date(rec.get("dataInicioSancao")),
        "end_date": _date(rec.get("dataFimSancao")),
        "sanction_type": (rec.get("tipoSancao") or {}).get("descricaoResumida"),
        "authority": ((rec.get("orgaoSancionador") or {}).get("nome") or "").strip() or None,
    }


def fetch_sancoes(c: ApiClient, source: str) -> list[dict]:
    """Pagina o cadastro inteiro (15 registros por página; o cache torna retomável)."""
    out, page = [], 1
    while True:
        data = c.get_json(source.lower(), {"pagina": page})
        if not data:
            break
        out += [s for s in (parse_sancao(source, r) for r in data) if s]
        page += 1
    return out
