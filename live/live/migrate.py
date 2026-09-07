"""Apply the live bot's own schema (the LIVE EDGE BOT block of db/schema.sql) idempotently. Everything in that block
is CREATE TABLE IF NOT EXISTS / ADD COLUMN IF NOT EXISTS / CREATE INDEX IF NOT EXISTS, so running it on every worker
start is safe. Nothing outside the block is executed: the pipeline's tables are the main agent's."""
from __future__ import annotations
import re
from pathlib import Path
from sqlalchemy import text
from nfl_edge import db
from nfl_edge.config import ROOT

MARK = "-- LIVE EDGE BOT (/live)"


def live_block() -> str:
    p = ROOT / "db" / "schema.sql"
    s = p.read_text()
    i = s.find(MARK)
    if i < 0:
        raise RuntimeError("live block not found in db/schema.sql")
    block = s[i:]
    # also the (moved) cards calibrated columns that precede the block — harmless and needed on a fresh DB
    pre = "ALTER TABLE cards ADD COLUMN IF NOT EXISTS prob_calibrated numeric;\nALTER TABLE cards ADD COLUMN IF NOT EXISTS edge_calibrated numeric;\n"
    return pre + block


def apply() -> int:
    stmts = [x.strip() for x in re.split(r";\s*\n", live_block()) if x.strip() and not all(l.strip().startswith("--") or not l.strip() for l in x.splitlines())]
    n = 0
    with db.conn() as c:
        for st in stmts:
            c.execute(text(st))
            n += 1
    have = db.read_sql("SELECT table_name FROM information_schema.tables WHERE table_name LIKE 'live\\_%%'").table_name.tolist()
    print(f"[migrate] {n} statements applied; live tables: {sorted(have)}")
    return n
