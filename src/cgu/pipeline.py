"""Orquestra as etapas: fonte -> modelo canônico -> detectores -> score -> validação."""

from __future__ import annotations

import time
from collections.abc import Callable

import pandas as pd

from cgu import db, schema
from cgu.config import Config
from cgu.detectors import benford, graph, isolation, overprice, redflags
from cgu.scoring import score, validate

DETECTORS: list[tuple[str, Callable]] = [
    ("isolation", isolation.run),
    ("benford", benford.run),
    ("overprice", overprice.run),
    ("graph", graph.run),
    ("redflags", redflags.run),
]


def _log(msg: str) -> None:
    print(f"[cgu] {msg}", flush=True)


def store_canonical(cfg: Config, tables: dict[str, pd.DataFrame], **meta: str) -> None:
    tables = schema.validate(tables)
    with db.connect(cfg.warehouse) as con:
        for (name,) in con.execute("SELECT table_name FROM information_schema.tables").fetchall():
            con.execute(f'DROP TABLE IF EXISTS "{name}"')
        for name, df in tables.items():
            db.write(con, name, df)
        db.set_meta(con, generated_at=pd.Timestamp.now().isoformat(timespec="seconds"), **meta)
    _log("modelo canônico gravado: " + ", ".join(f"{k}={len(v)}" for k, v in tables.items()))


def generate_synthetic(cfg: Config) -> None:
    from cgu.synthetic.generate import generate

    t0 = time.perf_counter()
    tables = generate(cfg)
    store_canonical(
        cfg,
        tables,
        source="synthetic",
        seed=str(cfg["synthetic"]["seed"]),
        uf=cfg["synthetic"]["uf"],
    )
    _log(f"base sintética gerada em {time.perf_counter() - t0:.1f}s")


def build_real(cfg: Config) -> None:
    from cgu.transform.build import build

    tables = build(cfg)
    store_canonical(
        cfg,
        tables,
        source="real",
        uf=cfg["real"]["uf"],
        start=str(cfg["real"]["start"]),
        end=str(cfg["real"]["end"]),
    )


def detect(cfg: Config) -> None:
    flags, aux = [], {}
    with db.connect(cfg.warehouse) as con:
        for name, fn in DETECTORS:
            t0 = time.perf_counter()
            out = fn(con, cfg)
            flags.append(out.pop("flags"))
            aux.update(out)
            n = int(flags[-1]["flag"].sum()) if not flags[-1].empty else 0
            _log(f"detector {name}: {n} contratos sinalizados ({time.perf_counter() - t0:.1f}s)")
        db.write(con, "flags", pd.concat(flags, ignore_index=True))
        for name, df in aux.items():
            db.write(con, name, df)


def run_score(cfg: Config) -> None:
    with db.connect(cfg.warehouse) as con:
        for name, df in score.run(con, cfg).items():
            db.write(con, name, df)
        top = db.read(
            con,
            "SELECT count(*) FILTER (WHERE risk >= 0.5) AS n, count(*) AS t FROM contract_score",
        ).iloc[0]
    _log(f"score calculado: {top.n} de {top.t} contratos com risco >= 0,5")


def run_validate(cfg: Config) -> dict:
    with db.connect(cfg.warehouse) as con:
        out = validate.run(con, cfg)
        for name, df in out.items():
            db.write(con, name, df)
    for r in out["validation_summary"].to_dict("records"):
        auc, p100 = r.get("auc", float("nan")), r.get("precision@100", float("nan"))
        _log(
            f"validação ({r['rotulo']}): AUC={auc:.3f}, precision@100={p100:.2f}, "
            f"taxa base={r['taxa_base']:.3f}"
        )
    for r in out["validation_scenario"].to_dict("records"):
        prec = "n/a" if r["precisao"] is None else f"{r['precisao']:.2f}"
        _log(
            f"  cenário {r['cenario']:<16} ({r['detector']:<15}) recall={r['recall']:.2f} "
            f"precisão={prec} [{r['acertos']}/{r['plantados']}, sinalizados={r['sinalizados']}]"
        )
    _log(f"relatório: {cfg.path('reports_dir') / 'validation.json'}")
    return out
