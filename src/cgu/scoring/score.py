"""Score de risco agregado por contrato, órgão e fornecedor.

Por contrato: noisy-OR dos indícios, risco = 1 - prod(1 - peso_i * score_i), em que o peso
é a gravidade configurada de cada detector. Um indício forte isolado já eleva o risco;
indícios independentes se acumulam sem passar de 1.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from cgu import db
from cgu.config import Config

DETECTOR_LABELS = {
    "shared_partners": "Sócios em comum entre concorrentes",
    "cartel": "Comunidade suspeita (Louvain)",
    "splitting": "Fracionamento de despesas",
    "overprice": "Sobrepreço",
    "single_supplier": "Fornecedor único recorrente",
    "new_company": "Empresa recém-criada",
    "isolation": "Contrato atípico (Isolation Forest)",
    "benford": "Desvio de Benford no órgão",
}


def contract_scores(
    flags: pd.DataFrame, contracts: pd.DataFrame, weights: dict[str, float]
) -> pd.DataFrame:
    active = flags[flags["flag"]]
    wide = (
        active.pivot_table(index="contract_id", columns="detector", values="score", aggfunc="max")
        .reindex(columns=list(weights))
        .fillna(0.0)
    )
    wide = wide.reindex(contracts["contract_id"]).fillna(0.0)
    w = np.array([weights[d] for d in wide.columns])
    risk = 1 - np.prod(1 - wide.to_numpy() * w, axis=1)
    out = contracts.set_index("contract_id").join(wide.add_prefix("s_"))
    out["risk"] = risk
    out["n_flags"] = (wide > 0).sum(axis=1).to_numpy()
    out["flags"] = [", ".join(d for d in wide.columns if row[d] > 0) for _, row in wide.iterrows()]
    return out.reset_index()


def run(con, cfg: Config) -> dict[str, pd.DataFrame]:
    weights = cfg["scoring"]["weights"]
    flags = db.table(con, "flags")
    contracts = db.read(
        con,
        """
        SELECT c.contract_id, c.tender_id, c.agency_id, a.name AS agency_name, c.cnpj,
               s.name AS supplier_name, c.modality, c.category, c.object, c.signed_at,
               c.value_initial, c.value_final
        FROM contract c
        LEFT JOIN agency a USING (agency_id)
        LEFT JOIN supplier s USING (cnpj)
    """,
    )
    cs = contract_scores(flags, contracts, weights)
    cs["value_at_risk"] = cs["value_final"] * cs["risk"]

    agency = cs.groupby(["agency_id", "agency_name"], as_index=False).agg(
        n_contracts=("contract_id", "count"),
        total_value=("value_final", "sum"),
        mean_risk=("risk", "mean"),
        p90_risk=("risk", lambda s: s.quantile(0.9)),
        value_at_risk=("value_at_risk", "sum"),
        n_high_risk=("risk", lambda s: int((s >= 0.5).sum())),
    )
    agency["risk_share_value"] = agency["value_at_risk"] / agency["total_value"]

    supplier = cs.groupby(["cnpj", "supplier_name"], as_index=False, dropna=False).agg(
        n_contracts=("contract_id", "count"),
        total_value=("value_final", "sum"),
        mean_risk=("risk", "mean"),
        max_risk=("risk", "max"),
        value_at_risk=("value_at_risk", "sum"),
    )
    return {"contract_score": cs, "agency_score": agency, "supplier_score": supplier}
