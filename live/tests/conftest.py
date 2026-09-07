import os
import pytest

os.environ.setdefault("LIVE_DRY_RUN", "1")


def db_ok() -> bool:
    try:
        from nfl_edge import db
        db.scalar("SELECT 1")
        return True
    except Exception:
        return False


needs_db = pytest.mark.skipif(not db_ok(), reason="no reachable DATABASE_URL")
