import numpy as np
import pandas as pd
from types import SimpleNamespace
from nfl_edge.models.spread import SpreadModel


class _Const:
    def __init__(self, v): self.v = v
    def predict(self, X): return np.full(len(X), self.v)


def test_p_home_cover_uses_empirical_residuals_and_half_pushes():
    m = SpreadModel(_Const(0.0), _Const(44.0), resid=np.array([-7, -3, -1, 0, 1, 3, 7], float), anchor_w=0.0, total_anchor_w=0.0)
    # bias = median = 0; projection 3 vs spread 3 → need resid > 0: 3 of 7 above, 1 push → 3/7 + 0.5/7
    p = m.p_home_cover(np.array([3.0]), np.array([3.0]))[0]
    assert abs(p - (3 / 7 + 0.5 / 7)) < 1e-9
    # projection well above the spread → high cover prob; below → low
    assert m.p_home_cover(np.array([10.0]), np.array([0.0]))[0] > 0.9
    assert m.p_home_cover(np.array([-10.0]), np.array([0.0]))[0] < 0.1


def test_bias_recentres_residuals():
    m = SpreadModel(_Const(0.0), _Const(44.0), resid=np.array([-4, -2, -1, 0, 1], float), anchor_w=0.0, total_anchor_w=0.0)
    assert m.bias == -1.0 and float(np.median(m.resid)) == 0.0
    X = pd.DataFrame({k: [0.0] for k in ["elo_diff", "epa_diff", "rest_diff", "div_game", "neutral", "qb_change_diff", "qb_inexp_diff", "early_season"]})
    assert m.predict_margin(X)[0] == -1.0


def test_grade_spread(monkeypatch):
    from nfl_edge.grading import grade
    games = pd.DataFrame([{"home_team": "KC", "away_team": "DEN", "home_score": 27, "away_score": 24}])
    monkeypatch.setattr(grade.db, "read_sql", lambda q, p=None: games)
    home_fav = SimpleNamespace(game_id="g", team="KC", line=-2.5, price_decimal=1.91)
    assert grade._grade_spread(home_fav)[1] == "win"            # KC −2.5 wins by 3
    assert grade._grade_spread(SimpleNamespace(game_id="g", team="KC", line=-3.0, price_decimal=1.91))[1] == "push"
    assert grade._grade_spread(SimpleNamespace(game_id="g", team="DEN", line=2.5, price_decimal=1.91))[1] == "loss"
    assert grade._grade_spread(SimpleNamespace(game_id="g", team="DEN", line=3.5, price_decimal=1.91))[1] == "win"
