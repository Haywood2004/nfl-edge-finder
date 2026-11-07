"""Read-only SQL for the master agent:  python ../agents/sql.py "SELECT ..."

Runs the statement inside a READ ONLY transaction, so the agents can inspect any table but can never write.
Prints at most 200 rows as tab-separated text. Run from /pipeline (uses nfl_edge.db for the connection).
"""
from __future__ import annotations
import sys
from sqlalchemy import text
from nfl_edge.db import engine


def main() -> int:
    if len(sys.argv) < 2 or not sys.argv[1].strip():
        print('usage: python ../agents/sql.py "SELECT ..."'); return 2
    stmt = sys.argv[1]
    with engine().connect() as c:
        c.execute(text("SET TRANSACTION READ ONLY"))
        try:
            res = c.execute(text(stmt))
        except Exception as e:  # show the DB error to the agent instead of a traceback
            print(f"SQL error: {e.__class__.__name__}: {str(e).splitlines()[0]}"); return 1
        if not res.returns_rows:
            print("(no rows returned)"); return 0
        cols = list(res.keys())
        rows = res.fetchmany(201)
    print("\t".join(cols))
    for r in rows[:200]:
        print("\t".join("" if v is None else str(v) for v in r))
    if len(rows) > 200:
        print("... (truncated at 200 rows; add LIMIT / filters)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
