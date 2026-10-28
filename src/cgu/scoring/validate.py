"""Validação do score.

1. Contra sanções (CEIS/CNEP), usadas só como rótulo, nunca como feature: o contrato é
   positivo se o fornecedor foi sancionado depois da assinatura. O rótulo é imperfeito
   (sanção depende de fiscalização, não só de fraude), então as métricas são indicativas.
2. No modo sintético, também contra o gabarito (`ground_truth`): precisão/recall de cada
   detector no cenário que ele deveria encontrar.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score, roc_curve

from cgu import db
from cgu.config import Config

# (cenário plantado, tipo de entidade, detector responsável)
SCENARIO_CHECKS = [
    ("cartel", "supplier", "cartel"),
    ("cartel", "tender", "shared_partners"),
    ("new_company", "supplier", "new_company"),
    ("splitting", "contract", "splitting"),
    ("overprice", "item", "overprice"),
    ("single_supplier", "contract", "single_supplier"),
    ("benford", "agency", "benford"),
    ("atypical", "contract", "isolation"),
]
KS = (50, 100, 200)


def ranking_metrics(score: pd.Series, label: pd.Series) -> dict:
    label = label.astype(int)
    order = np.argsort(-score.to_numpy(), kind="stable")
    y = label.to_numpy()[order]
    base = float(label.mean())
    out = {"n": int(len(label)), "positivos": int(label.sum()), "taxa_base": base}
    if 0 < label.sum() < len(label):
        out["auc"] = float(roc_auc_score(label, score))
    for k in KS:
        if k <= len(y):
            prec = float(y[:k].mean())
            out[f"precision@{k}"] = prec
            out[f"lift@{k}"] = prec / base if base else None
    return out


def roc_points(score: pd.Series, label: pd.Series, name: str) -> pd.DataFrame:
    if not 0 < label.sum() < len(label):
        return pd.DataFrame(columns=["label", "fpr", "tpr"])
    fpr, tpr, _ = roc_curve(label.astype(int), score)
    idx = np.unique(np.linspace(0, len(fpr) - 1, min(len(fpr), 200)).astype(int))
    return pd.DataFrame({"label": name, "fpr": fpr[idx], "tpr": tpr[idx]})


def _flagged(con, detector: str, entity: str) -> set[str]:
    if detector == "cartel" and entity == "supplier":
        return set(db.read(con, "SELECT cnpj FROM community_member WHERE community_flag")["cnpj"])
    if entity == "item":
        return set(db.read(con, "SELECT item_id FROM item_overprice WHERE flag")["item_id"])
    if entity == "agency":
        return set(
            db.read(con, "SELECT entity_id FROM benford WHERE entity_type = 'agency' AND flag")[
                "entity_id"
            ]
        )
    col = {"contract": "c.contract_id", "tender": "c.tender_id", "supplier": "c.cnpj"}[entity]
    return set(
        db.read(
            con,
            f"""
        SELECT DISTINCT {col} AS id FROM flags f JOIN contract c USING (contract_id)
        WHERE f.flag AND f.detector = ?""",
            [detector],
        )["id"]
    )


def run(con, cfg: Config) -> dict[str, pd.DataFrame]:
    cs = db.read(
        con,
        """
        SELECT cs.contract_id, cs.risk, cs.signed_at, cs.cnpj,
               EXISTS (SELECT 1 FROM sanction s WHERE s.cnpj = cs.cnpj
                       AND (s.start_date IS NULL OR s.start_date >= cs.signed_at)) AS sanctioned
        FROM contract_score cs
    """,
    )
    report: dict = {"sancoes": ranking_metrics(cs["risk"], cs["sanctioned"])}
    rocs = [roc_points(cs["risk"], cs["sanctioned"], "Sanções (CEIS/CNEP)")]

    flags = db.read(con, "SELECT contract_id, detector FROM flags WHERE flag")
    per_detector = []
    for det, g in flags.groupby("detector"):
        hit = cs["contract_id"].isin(g["contract_id"])
        rate_in = float(cs.loc[hit, "sanctioned"].mean()) if hit.any() else 0.0
        rate_out = float(cs.loc[~hit, "sanctioned"].mean()) if (~hit).any() else 0.0
        per_detector.append(
            {
                "detector": det,
                "contratos": int(hit.sum()),
                "taxa_sancao_com_flag": rate_in,
                "taxa_sancao_sem_flag": rate_out,
                "lift": rate_in / rate_out if rate_out else None,
            }
        )
    report["detectores_vs_sancoes"] = per_detector

    scenario_rows = []
    if db.has_table(con, "ground_truth"):
        gt = db.table(con, "ground_truth")
        fraud = set(gt.loc[gt.entity_type == "contract", "entity_id"])
        label = cs["contract_id"].isin(fraud)
        report["gabarito"] = ranking_metrics(cs["risk"], label)
        rocs.append(roc_points(cs["risk"], label, "Gabarito sintético"))
        for scenario, entity, detector in SCENARIO_CHECKS:
            truth = set(gt[(gt.scenario == scenario) & (gt.entity_type == entity)]["entity_id"])
            if not truth:
                continue
            found = _flagged(con, detector, entity)
            tp = len(found & truth)
            scenario_rows.append(
                {
                    "cenario": scenario,
                    "entidade": entity,
                    "detector": detector,
                    "plantados": len(truth),
                    "sinalizados": len(found),
                    "acertos": tp,
                    "recall": tp / len(truth),
                    "precisao": tp / len(found) if found else None,
                }
            )
        report["cenarios"] = scenario_rows

    out_dir = cfg.path("reports_dir")
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "validation.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)

    return {
        "validation_roc": pd.concat(rocs, ignore_index=True),
        "validation_scenario": pd.DataFrame(
            scenario_rows,
            columns=[
                "cenario",
                "entidade",
                "detector",
                "plantados",
                "sinalizados",
                "acertos",
                "recall",
                "precisao",
            ],
        ),
        "validation_detector": pd.DataFrame(per_detector),
        "validation_summary": pd.DataFrame(
            [
                {"rotulo": k, **{m: v for m, v in report[k].items()}}
                for k in ("sancoes", "gabarito")
                if k in report
            ]
        ),
    }
