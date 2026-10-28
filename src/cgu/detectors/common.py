"""Utilitários compartilhados pelos detectores."""

from __future__ import annotations

import json
from typing import Any

import numpy as np
import pandas as pd

FLAG_COLUMNS = ["contract_id", "detector", "score", "flag", "evidence"]


def to_json(obj: Any) -> str:
    def default(o: Any) -> Any:
        if isinstance(o, np.integer):
            return int(o)
        if isinstance(o, np.floating):
            return round(float(o), 4)
        if isinstance(o, pd.Timestamp):
            return o.date().isoformat()
        return str(o)

    return json.dumps(obj, ensure_ascii=False, default=default)


def flags_frame(rows: list[dict] | pd.DataFrame, detector: str) -> pd.DataFrame:
    df = pd.DataFrame(rows) if not isinstance(rows, pd.DataFrame) else rows.copy()
    if df.empty:
        return pd.DataFrame(columns=FLAG_COLUMNS)
    df["detector"] = detector
    df["score"] = df["score"].astype(float).clip(0, 1)
    df["flag"] = df["flag"].astype(bool)
    return df[FLAG_COLUMNS]
