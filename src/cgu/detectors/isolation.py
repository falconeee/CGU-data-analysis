"""Isolation Forest sobre atributos de contratos (contratos atípicos)."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

from cgu import db
from cgu.config import Config
from cgu.detectors.common import flags_frame, to_json

FEATURE_LABELS = {
    "log_value": "valor inicial (log)",
    "log_value_vs_category": "valor vs mediana da categoria (log)",
    "duration_days": "duração (dias)",
    "n_amendments": "nº de aditivos",
    "amendment_pct": "acréscimo por aditivos (fração do valor)",
    "n_bidders": "nº de licitantes",
    "publish_lag_days": "dias entre assinatura e publicação",
    "supplier_age_days": "idade da empresa na assinatura (dias)",
}

FEATURES_SQL = """
WITH nb AS (SELECT tender_id, count(*) AS n_bidders FROM bidder GROUP BY tender_id),
cat AS (
    SELECT category, median(value_initial) AS med FROM contract GROUP BY category
)
SELECT
    c.contract_id,
    c.modality,
    ln(c.value_initial + 1) AS log_value,
    ln(c.value_initial + 1) - ln(coalesce(cat.med, c.value_initial) + 1) AS log_value_vs_category,
    coalesce(date_diff('day', c.start_date, c.end_date), 0) AS duration_days,
    c.n_amendments,
    CASE WHEN c.value_initial > 0 THEN c.value_final / c.value_initial - 1 ELSE 0 END
        AS amendment_pct,
    coalesce(nb.n_bidders, 1) AS n_bidders,
    coalesce(date_diff('day', c.signed_at, c.published_at), 0) AS publish_lag_days,
    coalesce(date_diff('day', s.opened_at, c.signed_at), 3650) AS supplier_age_days
FROM contract c
LEFT JOIN nb ON nb.tender_id = c.tender_id
LEFT JOIN cat ON cat.category IS NOT DISTINCT FROM c.category
LEFT JOIN supplier s ON s.cnpj = c.cnpj
"""


def run(con, cfg: Config) -> dict[str, pd.DataFrame]:
    p = cfg["detectors"]["isolation"]
    feats = db.read(con, FEATURES_SQL)
    numeric = list(FEATURE_LABELS)
    X = pd.concat(
        [
            feats[numeric].astype(float),
            pd.get_dummies(feats["modality"], prefix="mod", dtype=float),
        ],
        axis=1,
    ).fillna(0)
    model = IsolationForest(
        n_estimators=p["n_estimators"], contamination=p["contamination"], random_state=0
    )
    model.fit(X)
    anomaly = -model.score_samples(X)
    pct = pd.Series(anomaly).rank(pct=True).to_numpy()
    flagged = model.predict(X) == -1

    # Desvio robusto de cada atributo, para explicar por que o contrato é atípico.
    med = X[numeric].median()
    iqr = (X[numeric].quantile(0.75) - X[numeric].quantile(0.25)).replace(0, 1)
    z = ((X[numeric] - med) / iqr).abs()

    rows = []
    for i, cid in enumerate(feats["contract_id"]):
        top = z.iloc[i].sort_values(ascending=False).head(3)
        rows.append(
            {
                "contract_id": cid,
                "score": float(np.clip((pct[i] - 0.95) / 0.05, 0, 1)),
                "flag": bool(flagged[i]),
                "evidence": to_json(
                    {
                        "percentil_anomalia": round(float(pct[i]) * 100, 1),
                        "principais_desvios": [
                            {
                                "atributo": FEATURE_LABELS[f],
                                "valor": round(float(X.iloc[i][f]), 2),
                                "mediana": round(float(med[f]), 2),
                            }
                            for f in top.index
                        ],
                    }
                ),
            }
        )
    return {"flags": flags_frame(rows, "isolation")}
