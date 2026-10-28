from __future__ import annotations

import json
from pathlib import Path

import pytest

from cgu import pipeline
from cgu.config import Config, load_config

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str):
    with open(FIXTURES / name, encoding="utf-8") as f:
        return json.load(f)


def tmp_config(tmp: Path, **overrides) -> Config:
    return load_config().with_overrides(
        **{
            "source": "synthetic",
            "paths.warehouse": str(tmp / "warehouse.duckdb"),
            "paths.reports_dir": str(tmp / "reports"),
            "paths.raw_dir": str(tmp / "raw"),
            **overrides,
        }
    )


@pytest.fixture(scope="session")
def synthetic_cfg(tmp_path_factory) -> Config:
    """Pipeline sintético completo, rodado uma vez para a sessão de testes."""
    cfg = tmp_config(tmp_path_factory.mktemp("pipeline"))
    pipeline.generate_synthetic(cfg)
    pipeline.detect(cfg)
    pipeline.run_score(cfg)
    pipeline.run_validate(cfg)
    return cfg
