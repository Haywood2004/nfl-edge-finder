"""The live bot writes only live_* tables and cards (source='live'). Static check over the package source:
every db.append / db.upsert / db.insert_returning_id / INSERT / UPDATE target must be a live_ table or cards."""
import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "live"
ALLOWED = {"live_snapshots", "live_lines", "live_alerts", "live_clv", "live_game_state", "live_projections", "cards", "odds_snapshots", "api_usage"}
# odds_snapshots: one row per poll is required because cards.snapshot_id references it (docs/LIVE.md); api_usage: credit log (pipeline's client).


def test_only_live_tables_written():
    bad = []
    for f in SRC.glob("*.py"):
        s = f.read_text()
        for m in re.finditer(r'db\.(append|upsert)\([^,]+,\s*"([a-z_]+)"', s):
            if m.group(2) not in ALLOWED: bad.append((f.name, m.group(0)))
        for m in re.finditer(r'insert_returning_id\("([a-z_]+)"', s):
            if m.group(1) not in ALLOWED: bad.append((f.name, m.group(0)))
        for m in re.finditer(r'(INSERT INTO|UPDATE)\s+([a-z_]+)', s):
            if m.group(2) not in ALLOWED: bad.append((f.name, m.group(0)))
        assert "DELETE " not in s.upper() and "TRUNCATE" not in s.upper(), f.name
    assert not bad, bad


def test_cards_rows_are_live_and_unpublished():
    s = (SRC / "pricing.py").read_text()
    assert '"source": "live"' in s
    a = (SRC / "alerts.py").read_text()
    assert "published=False" in a
