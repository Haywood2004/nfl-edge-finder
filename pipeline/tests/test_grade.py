"""Grader is market-aware: each prop market reads its own stat, voids on zero usage, moneylines use the final score."""
import pandas as pd
import pytest
from types import SimpleNamespace as NS
from nfl_edge.grading import grade


def _card(market="player_reception_yds", side="Over", line=60.5, dec=1.91, team="MIN", game_id="g1"):
    return NS(market=market, side=side, line=line, price_decimal=dec, player_id="p1", season=2026, week=1, team=team, game_id=game_id)


def test_receiving_yards_reads_receiving_column(monkeypatch):
    seen = {}
    def fake(sql, params=None):
        seen["sql"] = sql
        return pd.DataFrame({"stat": [75.0], "usage": [8]})
    monkeypatch.setattr(grade.db, "read_sql", fake)
    actual, result, profit = grade._grade_prop(_card())
    assert "receiving_yards" in seen["sql"] and "targets" in seen["sql"]
    assert (actual, result) == (75.0, "win") and profit == pytest.approx(0.91)


@pytest.mark.parametrize("market,cols", [("player_pass_yds", ("passing_yards", "attempts")), ("player_receptions", ("receptions", "targets")),
                                         ("player_rush_yds", ("rushing_yards", "carries"))])
def test_stat_columns_per_market(monkeypatch, market, cols):
    seen = {}
    monkeypatch.setattr(grade.db, "read_sql", lambda sql, p=None: (seen.setdefault("sql", sql), pd.DataFrame({"stat": [10.0], "usage": [3]}))[1])
    grade._grade_prop(_card(market=market, line=5.5))
    assert all(c in seen["sql"] for c in cols)


def test_zero_usage_is_void_not_under_win(monkeypatch):
    monkeypatch.setattr(grade.db, "read_sql", lambda sql, p=None: pd.DataFrame({"stat": [0.0], "usage": [0]}))
    actual, result, profit = grade._grade_prop(_card(side="Under"))
    assert result == "void" and profit == 0.0


def test_push_on_exact_line(monkeypatch):
    monkeypatch.setattr(grade.db, "read_sql", lambda sql, p=None: pd.DataFrame({"stat": [5.0], "usage": [6]}))
    assert grade._grade_prop(_card(market="player_receptions", line=5.0))[1] == "push"


def test_moneyline_uses_final_score(monkeypatch):
    monkeypatch.setattr(grade.db, "read_sql", lambda sql, p=None: pd.DataFrame({"home_team": ["MIN"], "away_team": ["GB"], "home_score": [24], "away_score": [20]}))
    margin, result, profit = grade._grade_moneyline(_card(market="h2h", team="GB", dec=2.4))
    assert (margin, result, profit) == (-4.0, "loss", -1.0)
    margin, result, profit = grade._grade_moneyline(_card(market="h2h", team="MIN", dec=1.6))
    assert result == "win" and profit == pytest.approx(0.6)
