from __future__ import annotations
import io
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


_TYPE_CACHE: dict[str, dict[str, str]] = {}


def _column_types(table: str) -> dict[str, str]:
    if table not in _TYPE_CACHE:
        r = read_sql("SELECT column_name, data_type FROM information_schema.columns WHERE table_name=:t", {"t": table})
        _TYPE_CACHE[table] = dict(zip(r.column_name, r.data_type))
    return _TYPE_CACHE[table]


def _coerce_types(df: pd.DataFrame, table: str) -> pd.DataFrame:
    """COPY is strict: '20.0' is not an integer and 'True' is not a bool literal for text CSV.
    Cast columns to the target table's declared types so pandas floats/objects serialize cleanly."""
    types = _column_types(table)
    df = df.copy()
    for c in df.columns:
        t = types.get(c)
        if t in ("integer", "bigint", "smallint"):
            df[c] = pd.to_numeric(df[c], errors="coerce").round().astype("Int64")
        elif t == "boolean":
            df[c] = df[c].map(lambda v: None if v is None or (isinstance(v, float) and pd.isna(v)) else bool(v))
    return df


def upsert(df: pd.DataFrame, table: str, keys: Iterable[str], chunk: int = 50000,
           update: bool = True) -> int:
    """Idempotent bulk upsert: COPY into a temp table, then INSERT ... ON CONFLICT (keys).

    One COPY + one INSERT per chunk instead of one round trip per row, which matters when the
    database is remote (Neon) — 450k plays load in ~1 minute instead of hours.
    """
    if df.empty:
        return 0
    df = _coerce_types(_clean(df), table)
    cols = list(df.columns)
    keys = list(keys)
    non_keys = [c for c in cols if c not in keys]
    action = (f"DO UPDATE SET " + ", ".join(f"{c} = EXCLUDED.{c}" for c in non_keys)) if (update and non_keys) else "DO NOTHING"
    col_sql = ", ".join(cols)
    n = 0
    raw = engine().raw_connection()
    try:
        cur = raw.cursor()
        tmp = f"_tmp_{table}"
        cur.execute(f"CREATE TEMP TABLE {tmp} (LIKE {table} INCLUDING DEFAULTS) ON COMMIT DROP")
        for i in range(0, len(df), chunk):
            buf = io.StringIO()
            df.iloc[i:i + chunk].to_csv(buf, index=False, header=False, na_rep="\\N")
            buf.seek(0)
            cur.copy_expert(f"COPY {tmp} ({col_sql}) FROM STDIN WITH (FORMAT csv, NULL '\\N')", buf)
            n += min(chunk, len(df) - i)
        cur.execute(f"INSERT INTO {table} ({col_sql}) SELECT {col_sql} FROM {tmp} "
                    f"ON CONFLICT ({', '.join(keys)}) {action}")
        raw.commit()
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.close()
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
