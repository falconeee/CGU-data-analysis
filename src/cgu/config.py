"""Carrega config.yaml e .env."""

from __future__ import annotations

import copy
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class Config:
    raw: dict[str, Any]
    root: Path = field(default=PROJECT_ROOT)

    def __getitem__(self, key: str) -> Any:
        return self.raw[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.raw.get(key, default)

    @property
    def source(self) -> str:
        return self.raw["source"]

    def path(self, key: str) -> Path:
        p = Path(self.raw["paths"][key])
        return p if p.is_absolute() else self.root / p

    @property
    def warehouse(self) -> Path:
        return self.path("warehouse")

    @property
    def api_key(self) -> str | None:
        return os.environ.get("CGU_API_KEY") or None

    def dispensa_limit(self, year: int, engineering: bool) -> float:
        """Limite de dispensa vigente no ano (usa o último ano configurado <= year)."""
        limits = self.raw["dispensa_limits"]
        years = sorted(limits)
        eligible = [y for y in years if y <= year]
        y = eligible[-1] if eligible else years[0]
        return float(limits[y]["engineering" if engineering else "other"])

    def with_overrides(self, **overrides: Any) -> Config:
        """Retorna uma cópia com chaves de topo/aninhadas ("a.b") sobrescritas."""
        raw = copy.deepcopy(self.raw)
        for dotted, value in overrides.items():
            if value is None:
                continue
            node = raw
            *parents, leaf = dotted.split(".")
            for p in parents:
                node = node.setdefault(p, {})
            node[leaf] = value
        return Config(raw=raw, root=self.root)


def load_config(path: str | Path | None = None) -> Config:
    load_dotenv(PROJECT_ROOT / ".env")
    path = Path(path or os.environ.get("CGU_CONFIG") or PROJECT_ROOT / "config.yaml")
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return Config(raw=raw, root=path.resolve().parent)
