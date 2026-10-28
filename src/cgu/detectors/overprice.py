"""Sobrepreço: preço unitário do item vs preço de referência por item/UF/ano.

A referência externa (ref_price) tem prioridade; sem ela (ou com poucas observações),
usa a distribuição interna dos próprios itens do mesmo código/UF/ano.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from cgu.config import Config
from cgu.detectors.common import flags_frame, to_json

SQL = """
WITH it AS (
    SELECT *, year(date) AS year FROM item WHERE item_code IS NOT NULL AND unit_price > 0
),
internal AS (
    SELECT item_code, uf, year,
           median(unit_price) AS median,
           quantile_cont(unit_price, 0.25) AS q1,
           quantile_cont(unit_price, 0.75) AS q3,
           count(*) AS n_obs
    FROM it GROUP BY ALL
),
ext AS (SELECT * FROM ref_price WHERE n_obs >= $min_obs)
SELECT it.item_id, it.contract_id, it.item_code, it.description, it.unit, it.quantity,
       it.unit_price, it.uf, it.year,
       coalesce(ext.median, internal.median) AS ref_median,
       coalesce(ext.q1, internal.q1) AS ref_q1,
       coalesce(ext.q3, internal.q3) AS ref_q3,
       coalesce(ext.n_obs, internal.n_obs) AS ref_n,
       CASE WHEN ext.median IS NOT NULL THEN 'externa' ELSE 'interna' END AS ref_source
FROM it
LEFT JOIN ext USING (item_code, uf, year)
LEFT JOIN internal USING (item_code, uf, year)
"""


def run(con, cfg: Config) -> dict[str, pd.DataFrame]:
    p = cfg["detectors"]["overprice"]
    df = con.execute(SQL, {"min_obs": p["min_ref_obs"]}).df()
    df = df[df["ref_n"] >= p["min_ref_obs"]].copy()
    df["ratio"] = df["unit_price"] / df["ref_median"]
    iqr = df["ref_q3"] - df["ref_q1"]
    df["threshold"] = np.maximum(
        df["ref_q3"] + p["iqr_k"] * iqr, p["ratio_threshold"] * df["ref_median"]
    )
    df["flag"] = df["unit_price"] > df["threshold"]
    df["score"] = np.where(df["flag"], np.clip((df["ratio"] - 1) / 2, 0, 1), 0.0)
    df["excess_value"] = np.where(
        df["flag"], (df["unit_price"] - df["ref_median"]) * df["quantity"], 0.0
    )

    flagged = df[df["flag"] & df["contract_id"].notna()]
    rows = []
    for cid, g in flagged.groupby("contract_id"):
        top = g.sort_values("ratio", ascending=False).iloc[0]
        rows.append(
            {
                "contract_id": cid,
                "score": g["score"].max(),
                "flag": True,
                "evidence": to_json(
                    {
                        "itens_com_sobrepreco": len(g),
                        "sobrepreco_estimado": round(float(g["excess_value"].sum()), 2),
                        "item_mais_caro": {
                            "descricao": top["description"],
                            "preco": round(top["unit_price"], 2),
                            "referencia": round(top["ref_median"], 2),
                            "razao": round(top["ratio"], 2),
                            "fonte_ref": top["ref_source"],
                        },
                    }
                ),
            }
        )
    out = df[
        [
            "item_id",
            "contract_id",
            "item_code",
            "description",
            "unit",
            "quantity",
            "unit_price",
            "uf",
            "year",
            "ref_median",
            "ref_q1",
            "ref_q3",
            "ref_n",
            "ref_source",
            "ratio",
            "threshold",
            "flag",
            "score",
            "excess_value",
        ]
    ]
    return {"flags": flags_frame(rows, "overprice"), "item_overprice": out}
