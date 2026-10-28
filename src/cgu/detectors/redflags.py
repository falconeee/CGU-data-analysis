"""Red flags baseadas em regras.

- Sócios em comum entre concorrentes da mesma licitação.
- Empresa recém-criada na data do contrato.
- Fracionamento de despesas: dispensas que, somadas numa janela, ultrapassam o limite legal.
- Fornecedor único recorrente no órgão.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from cgu import db
from cgu.config import Config
from cgu.detectors.common import flags_frame, to_json

SHARED_PARTNERS_SQL = """
WITH b AS (SELECT tender_id, cnpj, substr(cnpj, 1, 8) AS base FROM bidder),
pairs AS (
    SELECT b1.tender_id, b1.cnpj AS cnpj_a, b2.cnpj AS cnpj_b,
           p1.partner_name AS link
    FROM b b1
    JOIN b b2 ON b1.tender_id = b2.tender_id AND b1.cnpj < b2.cnpj
    JOIN partner p1 ON p1.cnpj_base = b1.base
    JOIN partner p2 ON p2.cnpj_base = b2.base
     AND p1.partner_name = p2.partner_name
     AND p1.partner_doc IS NOT DISTINCT FROM p2.partner_doc
    UNION
    SELECT b1.tender_id, b1.cnpj, b2.cnpj, 'mesmo CNPJ básico'
    FROM b b1 JOIN b b2 ON b1.tender_id = b2.tender_id AND b1.base = b2.base
     AND b1.cnpj < b2.cnpj
)
SELECT c.contract_id, p.tender_id, p.cnpj_a, p.cnpj_b, p.link
FROM pairs p JOIN contract c ON c.tender_id = p.tender_id
"""


def shared_partners(con, cfg: Config) -> pd.DataFrame:
    df = db.read(con, SHARED_PARTNERS_SQL)
    rows = []
    for cid, g in df.groupby("contract_id"):
        n_pairs = g[["cnpj_a", "cnpj_b"]].drop_duplicates().shape[0]
        rows.append(
            {
                "contract_id": cid,
                "score": min(1.0, 0.7 + 0.15 * (n_pairs - 1)),
                "flag": True,
                "evidence": to_json(
                    {
                        "licitacao": g["tender_id"].iloc[0],
                        "pares": [
                            {"empresa_a": r.cnpj_a, "empresa_b": r.cnpj_b, "vinculo": r.link}
                            for r in g.itertuples()
                        ],
                    }
                ),
            }
        )
    return flags_frame(rows, "shared_partners")


def new_company(con, cfg: Config) -> pd.DataFrame:
    max_age = cfg["detectors"]["new_company"]["max_age_days"]
    df = db.read(
        con,
        """
        SELECT c.contract_id, c.signed_at, s.opened_at, c.value_final,
               date_diff('day', s.opened_at, c.signed_at) AS age_days
        FROM contract c JOIN supplier s ON s.cnpj = c.cnpj
        WHERE s.opened_at IS NOT NULL
    """,
    )
    df = df[(df["age_days"] >= 0) & (df["age_days"] < max_age)].copy()
    df["score"] = 1 - df["age_days"] / max_age
    df["flag"] = True
    df["evidence"] = [
        to_json({"abertura": r.opened_at, "assinatura": r.signed_at, "idade_dias": r.age_days})
        for r in df.itertuples()
    ]
    return flags_frame(df, "new_company")


def _splitting_windows(g: pd.DataFrame, window: int, near: float, min_count: int) -> list:
    """Janelas deslizantes de dispensas que somadas ultrapassam o limite."""
    g = g.sort_values("signed_at")
    dates = g["signed_at"].to_numpy()
    out = []
    for i in range(len(g)):
        lo = dates[i] - np.timedelta64(window, "D")
        w = g[(g["signed_at"] >= lo) & (g["signed_at"] <= dates[i])]
        limit = w["limit"].max()
        if (
            len(w) >= min_count
            and w["value_initial"].sum() > limit
            and (w["value_initial"] < w["limit"]).all()
            and (w["value_initial"] >= near * w["limit"]).mean() >= 0.5
        ):
            out.append(w)
    return out


def splitting(con, cfg: Config) -> pd.DataFrame:
    p = cfg["detectors"]["splitting"]
    df = db.read(
        con,
        """
        SELECT c.contract_id, c.agency_id, c.cnpj, c.category, c.signed_at, c.value_initial,
               coalesce(cat.engineering, false) AS engineering
        FROM contract c LEFT JOIN category cat ON cat.category_id = c.category
        WHERE c.modality = 'dispensa'
    """,
    )
    if df.empty:
        return flags_frame([], "splitting")
    df["limit"] = [
        cfg.dispensa_limit(d.year, e) for d, e in zip(df.signed_at, df.engineering, strict=True)
    ]
    best: dict[str, dict] = {}
    for keys, label in (
        (["agency_id", "category"], "mesma categoria"),
        (["agency_id", "cnpj"], "mesmo fornecedor"),
    ):
        for _, g in df.groupby(keys, dropna=False):
            if len(g) < p["min_count"]:
                continue
            for w in _splitting_windows(g, p["window_days"], p["near_limit_ratio"], p["min_count"]):
                total, limit = w["value_initial"].sum(), w["limit"].max()
                score = max(0.5, min(1.0, total / limit / 2))
                ev = {
                    "criterio": label,
                    "n_dispensas": len(w),
                    "inicio": w["signed_at"].min(),
                    "fim": w["signed_at"].max(),
                    "soma": round(total, 2),
                    "limite": limit,
                    "contratos": w["contract_id"].tolist(),
                    "fornecedores": sorted(w["cnpj"].unique().tolist()),
                }
                for cid in w["contract_id"]:
                    if cid not in best or best[cid]["score"] < score:
                        best[cid] = {
                            "contract_id": cid,
                            "score": score,
                            "flag": True,
                            "evidence": to_json(ev),
                        }
    return flags_frame(list(best.values()), "splitting")


def single_supplier(con, cfg: Config) -> pd.DataFrame:
    p = cfg["detectors"]["single_supplier"]
    df = db.read(
        con,
        """
        WITH nb AS (SELECT tender_id, count(*) AS n FROM bidder GROUP BY tender_id),
        c AS (
            SELECT c.*, nb.n AS n_bidders,
                   sum(c.value_final) OVER (PARTITION BY c.agency_id) AS agency_total
            FROM contract c LEFT JOIN nb ON nb.tender_id = c.tender_id
        )
        SELECT agency_id, cnpj, count(*) AS n_contracts,
               sum(value_final) / any_value(agency_total) AS value_share,
               avg(CASE WHEN n_bidders = 1 THEN 1.0 ELSE 0.0 END) AS single_bid_ratio,
               list(contract_id) AS contracts
        FROM c GROUP BY agency_id, cnpj
    """,
    )
    hit = df[
        (df["n_contracts"] >= p["min_contracts"])
        & (
            (df["value_share"] >= p["min_value_share"])
            | (df["single_bid_ratio"] >= p["min_single_bid_ratio"])
        )
    ]
    rows = []
    for r in hit.itertuples():
        score = min(1.0, 0.5 * min(1.0, r.value_share / 0.3) + 0.5 * r.single_bid_ratio)
        ev = to_json(
            {
                "orgao": r.agency_id,
                "n_contratos": r.n_contracts,
                "participacao_no_valor": round(r.value_share, 4),
                "proporcao_licitante_unico": round(r.single_bid_ratio, 4),
            }
        )
        rows += [
            {"contract_id": cid, "score": score, "flag": True, "evidence": ev}
            for cid in r.contracts
        ]
    return flags_frame(rows, "single_supplier")


def run(con, cfg: Config) -> dict[str, pd.DataFrame]:
    flags = pd.concat(
        [
            shared_partners(con, cfg),
            new_company(con, cfg),
            splitting(con, cfg),
            single_supplier(con, cfg),
        ],
        ignore_index=True,
    )
    return {"flags": flags}
