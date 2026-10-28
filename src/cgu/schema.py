"""Modelo canônico: contrato entre as fontes (sintética/real) e os detectores.

Tanto o gerador sintético quanto o transform dos dados reais produzem exatamente estas
tabelas; detectores, score e dashboard só conhecem este formato.
"""

from __future__ import annotations

import pandas as pd
import pandera.pandas as pa
from pandera.pandas import Check, Column

MODALITIES = ["pregao", "concorrencia", "dispensa", "inexigibilidade", "outra"]
COMPETITIVE = {"pregao", "concorrencia"}
SPHERES = ["federal", "estadual", "municipal"]
SANCTION_SOURCES = ["CEIS", "CNEP"]

_cnpj = Check.str_matches(r"^[A-Z0-9]{12}[0-9]{2}$")


def _str(nullable: bool = False, **kw) -> Column:
    return Column(str, nullable=nullable, coerce=True, **kw)


def _date(nullable: bool = False) -> Column:
    return Column("datetime64[ns]", nullable=nullable, coerce=True)


def _float(nullable: bool = False, **kw) -> Column:
    return Column(float, nullable=nullable, coerce=True, **kw)


SCHEMAS: dict[str, pa.DataFrameSchema] = {
    "agency": pa.DataFrameSchema(
        {
            "agency_id": _str(unique=True),
            "name": _str(),
            "sphere": _str(checks=Check.isin(SPHERES)),
            "uf": _str(),
            "municipality": _str(nullable=True),
        }
    ),
    "category": pa.DataFrameSchema(
        {
            "category_id": _str(unique=True),
            "name": _str(),
            # Obras/serviços de engenharia usam o limite de dispensa do art. 75, I.
            "engineering": Column(bool, coerce=True),
        }
    ),
    "supplier": pa.DataFrameSchema(
        {
            "cnpj": _str(unique=True, checks=_cnpj),
            "cnpj_base": _str(),
            "name": _str(),
            "opened_at": _date(nullable=True),
            "uf": _str(nullable=True),
            "size": _str(nullable=True),
        }
    ),
    "partner": pa.DataFrameSchema(
        {
            "cnpj_base": _str(),
            "partner_name": _str(),
            "partner_doc": _str(nullable=True),  # CPF mascarado, como na Receita
            "joined_at": _date(nullable=True),
        }
    ),
    "tender": pa.DataFrameSchema(
        {
            "tender_id": _str(unique=True),
            "agency_id": _str(),
            "modality": _str(checks=Check.isin(MODALITIES)),
            "category": _str(nullable=True),
            "object": _str(nullable=True),
            "published_at": _date(),
            "estimated_value": _float(nullable=True),
        }
    ),
    "bidder": pa.DataFrameSchema(
        {
            "tender_id": _str(),
            "cnpj": _str(checks=_cnpj),
            "bid_value": _float(nullable=True),
            "is_winner": Column(bool, coerce=True),
        },
        unique=["tender_id", "cnpj"],
    ),
    "contract": pa.DataFrameSchema(
        {
            "contract_id": _str(unique=True),
            "tender_id": _str(nullable=True),
            "agency_id": _str(),
            "cnpj": _str(checks=_cnpj),
            "modality": _str(checks=Check.isin(MODALITIES)),
            "category": _str(nullable=True),
            "object": _str(nullable=True),
            "signed_at": _date(),
            "published_at": _date(nullable=True),
            "start_date": _date(nullable=True),
            "end_date": _date(nullable=True),
            "value_initial": _float(checks=Check.ge(0)),
            "value_final": _float(checks=Check.ge(0)),
            "n_amendments": Column(int, coerce=True, checks=Check.ge(0)),
        }
    ),
    "item": pa.DataFrameSchema(
        {
            "item_id": _str(unique=True),
            "tender_id": _str(),
            "contract_id": _str(nullable=True),
            "item_code": _str(nullable=True),
            "description": _str(nullable=True),
            "unit": _str(nullable=True),
            "quantity": _float(checks=Check.ge(0)),
            "unit_price": _float(checks=Check.ge(0)),
            "uf": _str(nullable=True),
            "date": _date(),
        }
    ),
    "ref_price": pa.DataFrameSchema(
        {
            "item_code": _str(),
            "uf": _str(),
            "year": Column(int, coerce=True),
            "median": _float(),
            "q1": _float(),
            "q3": _float(),
            "n_obs": Column(int, coerce=True),
        },
        unique=["item_code", "uf", "year"],
    ),
    "sanction": pa.DataFrameSchema(
        {
            "cnpj": _str(checks=_cnpj),
            "source": _str(checks=Check.isin(SANCTION_SOURCES)),
            "start_date": _date(nullable=True),
            "end_date": _date(nullable=True),
            "sanction_type": _str(nullable=True),
            "authority": _str(nullable=True),
        }
    ),
}

# Só existe no modo sintético: gabarito dos cenários plantados.
GROUND_TRUTH = pa.DataFrameSchema(
    {
        "entity_type": _str(
            checks=Check.isin(["contract", "supplier", "agency", "tender", "item"])
        ),
        "entity_id": _str(),
        "scenario": _str(),
    }
)


def validate(tables: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Valida e converte tipos de todas as tabelas canônicas (levanta erro se faltar alguma)."""
    missing = set(SCHEMAS) - set(tables)
    if missing:
        raise ValueError(f"Tabelas canônicas ausentes: {sorted(missing)}")
    out = {name: SCHEMAS[name].validate(tables[name], lazy=True) for name in SCHEMAS}
    if "ground_truth" in tables:
        out["ground_truth"] = GROUND_TRUTH.validate(tables["ground_truth"], lazy=True)
    return out
