"""Point-in-time guarantees (brief §6)."""
import pandas as pd
import pytest
from nfl_edge import db


def _has_db():
    try:
        db.scalar("select 1"); return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _has_db(), reason="no database")


def test_every_feature_row_as_of_before_kickoff():
    n = db.scalar("SELECT count(*) FROM feat_player_game WHERE as_of >= kickoff_utc")
    assert n == 0


def test_team_features_as_of_before_first_kickoff():
    n = db.scalar("""SELECT count(*) FROM feat_team_defense d JOIN (
                        SELECT season, week, min(kickoff_utc) k FROM raw_games GROUP BY 1,2) g USING (season, week)
                     WHERE d.as_of >= g.k""")
    assert n == 0


def test_defense_features_only_use_prior_weeks():
    """Week-1 defense features must not depend on the current season at all."""
    r = db.read_sql("SELECT games FROM feat_team_defense WHERE week=1")
    assert (r.games == 0).all()


def test_player_rolling_features_shift():
    """A QB's py_l3 for week w must equal the mean of his starter games strictly before w."""
    import json
    r = db.read_sql("""SELECT player_id, season, week, features FROM feat_player_game
                       WHERE season=2025 AND week=10 AND target_attempts>=10 LIMIT 5""")
    for _, x in r.iterrows():
        f = json.loads(x.features) if isinstance(x.features, str) else x.features
        hist = db.read_sql("""SELECT passing_yards FROM raw_weekly_stats WHERE player_id=:p AND attempts>=10
                              AND season_type='REG' AND (season<:s OR (season=:s AND week<:w))
                              ORDER BY season DESC, week DESC LIMIT 3""", {"p": x.player_id, "s": 2025, "w": 10})
        if len(hist) == 3:
            assert abs(hist.passing_yards.mean() - f["py_l3"]) < 1e-6
