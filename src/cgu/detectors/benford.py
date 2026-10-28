"""Lei de Benford nos valores (1º e 2º dígitos) por órgão e por fornecedor."""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

from cgu import db
from cgu.config import Config
from cgu.detectors.common import flags_frame, to_json

FIRST = np.log10(1 + 1 / np.arange(1, 10))
SECOND = np.array(
    [sum(np.log10(1 + 1 / (10 * d1 + d2)) for d1 in range(1, 10)) for d2 in range(10)]
)

# Valores analisados: valor inicial dos contratos + total de cada item (qtd x preço).
VALUES_SQL = """
SELECT c.agency_id, c.cnpj, c.value_initial AS value FROM contract c
UNION ALL
SELECT c.agency_id, c.cnpj, i.quantity * i.unit_price AS value
FROM item i JOIN contract c ON c.contract_id = i.contract_id
"""


def mad_class(mad: float) -> str:
    """Faixas de conformidade de Nigrini para o 1º dígito."""
    if mad <= 0.006:
        return "conformidade próxima"
    if mad <= 0.012:
        return "conformidade aceitável"
    if mad <= 0.015:
        return "conformidade marginal"
    return "não conformidade"


def digits(values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    v = values[values >= 10]
    e = np.floor(np.log10(v))
    lead2 = np.floor(v / 10 ** (e - 1)).astype(int)  # dois primeiros dígitos (10..99)
    # corrige arredondamentos de ponto flutuante em potências de 10
    lead2 = np.where(lead2 < 10, lead2 * 10, np.where(lead2 > 99, lead2 // 10, lead2))
    return lead2 // 10, lead2 % 10


def analyze(values: np.ndarray) -> dict:
    d1, d2 = digits(np.asarray(values, dtype=float))
    n = len(d1)
    if n == 0:
        return {"n": 0}
    obs1 = np.bincount(d1, minlength=10)[1:10]
    obs2 = np.bincount(d2, minlength=10)
    p1, p2 = obs1 / n, obs2 / n
    chi2, pval = stats.chisquare(obs1, FIRST * n)
    v = np.asarray(values, dtype=float)
    v = v[v >= 10]
    return {
        "n": n,
        "chi2": float(chi2),
        "p_value": float(pval),
        "mad": float(np.mean(np.abs(p1 - FIRST))),
        "mad2": float(np.mean(np.abs(p2 - SECOND))),
        "round_share": float(np.mean(np.isclose(np.mod(v, 100), 0))),
        "observed": p1.round(4).tolist(),
        "observed2": p2.round(4).tolist(),
    }


def run(con, cfg: Config) -> dict[str, pd.DataFrame]:
    p = cfg["detectors"]["benford"]
    values = db.read(con, VALUES_SQL)
    rows = []
    for entity_type, key in (("agency", "agency_id"), ("supplier", "cnpj")):
        for entity_id, g in values.groupby(key):
            r = analyze(g["value"].to_numpy())
            if r["n"] == 0:
                continue
            enough = r["n"] >= p["min_n"]
            flag = enough and r["p_value"] < p["p_value"] and r["mad"] > p["mad_conformity"]
            score = float(np.clip((r["mad"] - p["mad_conformity"]) / 0.02, 0, 1)) if flag else 0.0
            rows.append(
                {
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    **r,
                    "mad_class": mad_class(r["mad"]),
                    "enough_data": enough,
                    "flag": flag,
                    "score": score,
                }
            )
    bf = pd.DataFrame(rows)
    bf["observed"] = bf["observed"].map(to_json)
    bf["observed2"] = bf["observed2"].map(to_json)

    # Indício propagado para os contratos do órgão reprovado.
    agencies = bf[(bf.entity_type == "agency") & bf.flag].set_index("entity_id")
    contracts = db.read(con, "SELECT contract_id, agency_id FROM contract")
    contracts = contracts[contracts.agency_id.isin(agencies.index)]
    flag_rows = [
        {
            "contract_id": r.contract_id,
            "score": agencies.at[r.agency_id, "score"],
            "flag": True,
            "evidence": to_json(
                {
                    "nivel": "órgão",
                    "orgao": r.agency_id,
                    "n_valores": agencies.at[r.agency_id, "n"],
                    "mad": agencies.at[r.agency_id, "mad"],
                    "p_valor": agencies.at[r.agency_id, "p_value"],
                    "classe": agencies.at[r.agency_id, "mad_class"],
                }
            ),
        }
        for r in contracts.itertuples()
    ]
    return {"flags": flags_frame(flag_rows, "benford"), "benford": bf}
