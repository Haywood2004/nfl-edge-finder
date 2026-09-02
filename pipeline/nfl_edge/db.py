from __future__ import annotations
import json
from contextlib import contextmanager
from typing import Iterable
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from .config import DATABASE_URL

_engine: Engine | None = None


def engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True)
    return _engine


@contextmanager
def conn():
    with engine().begin() as c:
        yield c


def read_sql(sql: str, params: dict | None = None) -> pd.DataFrame:
    with engine().connect() as c:
        return pd.read_sql(text(sql), c, params=params or {})


def scalar(sql: str, params: dict | None = None):
    with engine().connect() as c:
        return c.execute(text(sql), params or {}).scalar()


def execute(sql: str, params: dict | list[dict] | None = None):
    with conn() as c:
        return c.execute(text(sql), params or {})


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    """NaN → None so psycopg2 writes NULLs; dict/list → JSON strings."""
    df = df.astype(object).where(pd.notnull(df), None)

    def _is_json(v):  # dicts and lists containing dicts/lists → jsonb; flat lists → Postgres arrays
        return isinstance(v, dict) or (isinstance(v, list) and any(isinstance(x, (dict, list)) for x in v))

    for col in df.columns:
        if df[col].map(_is_json).any():
            df[col] = df[col].map(lambda v: json.dumps(v) if _is_json(v) else v)
    return df


def upsert(df: pd.DataFrame, table: str, keys: Iterable[str], chunk: int = 5000,
           update: bool = True) -> int:
    """Idempotent INSERT ... ON CONFLICT (keys) DO UPDATE / NOTHING. Returns rows sent."""
    if df.empty:
        return 0
    df = _clean(df)
    cols = list(df.columns)
    keys = list(keys)
    col_sql = ", ".join(cols)
    val_sql = ", ".join(f":{c}" for c in cols)
    non_keys = [c for c in cols if c not in keys]
    if update and non_keys:
        set_sql = ", ".join(f"{c} = EXCLUDED.{c}" for c in non_keys)
        action = f"DO UPDATE SET {set_sql}"
    else:
        action = "DO NOTHING"
    sql = text(f"INSERT INTO {table} ({col_sql}) VALUES ({val_sql}) "
               f"ON CONFLICT ({', '.join(keys)}) {action}")
    n = 0
    with conn() as c:
        for i in range(0, len(df), chunk):
            rows = df.iloc[i:i + chunk].to_dict("records")
            c.execute(sql, rows)
            n += len(rows)
    return n


def insert_returning_id(table: str, row: dict) -> int:
    cols = list(row)
    sql = text(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(':'+c for c in cols)}) RETURNING id")
    with conn() as c:
        return c.execute(sql, _clean(pd.DataFrame([row])).iloc[0].to_dict()).scalar()


def append(df: pd.DataFrame, table: str, chunk: int = 5000) -> int:
    """Plain append (for append-only tables)."""
    if df.empty:
        return 0
    df = _clean(df)
    cols = list(df.columns)
    sql = text(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(':'+c for c in cols)})")
    n = 0
    with conn() as c:
        for i in range(0, len(df), chunk):
            rows = df.iloc[i:i + chunk].to_dict("records")
            c.execute(sql, rows)
            n += len(rows)
    return n


class JobRun:
    """Context manager that records a row in pipeline_runs."""

    def __init__(self, job: str):
        self.job = job
        self.id = None
        self.rows = None
        self.detail: dict = {}

    def __enter__(self):
        self.id = insert_returning_id("pipeline_runs", {"job": self.job})
        return self

    def __exit__(self, exc_type, exc, tb):
        status = "failed" if exc else "ok"
        if exc:
            self.detail["error"] = repr(exc)
        execute("UPDATE pipeline_runs SET finished_at=now(), status=:s, rows=:r, detail=:d WHERE id=:id",
                {"s": status, "r": self.rows, "d": json.dumps(self.detail), "id": self.id})
        return False
