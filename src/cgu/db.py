"""Acesso ao warehouse DuckDB."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import duckdb
import pandas as pd


@contextmanager
def connect(path: Path, read_only: bool = False):
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path), read_only=read_only)
    try:
        yield con
    finally:
        con.close()


def write(con: duckdb.DuckDBPyConnection, name: str, df: pd.DataFrame) -> None:
    con.register("_df", df)
    con.execute(f'CREATE OR REPLACE TABLE "{name}" AS SELECT * FROM _df')
    con.unregister("_df")


def read(con: duckdb.DuckDBPyConnection, sql: str, params: list | None = None) -> pd.DataFrame:
    return con.execute(sql, params or []).df()


def table(con: duckdb.DuckDBPyConnection, name: str) -> pd.DataFrame:
    return read(con, f'SELECT * FROM "{name}"')


def has_table(con: duckdb.DuckDBPyConnection, name: str) -> bool:
    return bool(
        con.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_name = ?", [name]
        ).fetchone()[0]
    )


def set_meta(con: duckdb.DuckDBPyConnection, **values: str) -> None:
    con.execute('CREATE TABLE IF NOT EXISTS "meta" (key VARCHAR PRIMARY KEY, value VARCHAR)')
    for k, v in values.items():
        con.execute('INSERT OR REPLACE INTO "meta" VALUES (?, ?)', [k, str(v)])


def get_meta(con: duckdb.DuckDBPyConnection) -> dict[str, str]:
    if not has_table(con, "meta"):
        return {}
    return dict(con.execute('SELECT key, value FROM "meta"').fetchall())
