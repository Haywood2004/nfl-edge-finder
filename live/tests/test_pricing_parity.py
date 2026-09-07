"""Live pricing must reproduce the pipeline's own cards for the same lines (model_prob, confidence, calibrated p)."""
import pandas as pd
import pytest
from conftest import needs_db


@needs_db
def test_live_pricing_matches_pipeline_cards():
    from nfl_edge import db
    from live.pricing import WeekContext
    cards = db.read_sql("""SELECT c.*, s.id AS sid FROM cards c JOIN odds_snapshots s ON s.id = c.snapshot_id
                           WHERE c.source='model' AND c.market='player_pass_yds'
                             AND c.snapshot_id = (SELECT max(snapshot_id) FROM cards WHERE source='model' AND market='player_pass_yds')""")
    if cards.empty:
        pytest.skip("no pipeline cards in this DB")
    ctx = WeekContext(int(cards.season.iloc[0]), int(cards.week.iloc[0]))
    snap = int(cards.sid.iloc[0])
    lines = db.read_sql("SELECT * FROM odds_lines WHERE snapshot_id=:s AND market='player_pass_yds'", {"s": snap})
    rows = []
    for eid, g in lines.groupby("event_id"):
        for c in ctx.price("player_pass_yds", eid, g):
            rows.append({"player_name": c.player_name, "side": c.side, "live_mp": c.model_prob, "live_conf": c.confidence, "live_pcal": c.prob_calibrated, "live_book": c.book})
    live = pd.DataFrame(rows)
    m = cards.merge(live, on=["player_name", "side"], how="inner")
    assert len(m) >= 0.9 * len(cards)
    assert (m.live_mp - m.model_prob.astype(float)).abs().max() < 1e-9
    assert (m.live_conf - m.confidence).abs().max() == 0
    assert (m.live_book == m.book).all()
    if m.prob_calibrated.notna().any():
        assert (m.live_pcal.astype(float) - m.prob_calibrated.astype(float)).abs().max() < 1e-9
