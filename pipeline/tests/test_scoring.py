from nfl_edge.scoring.factors import build_factors, confidence_score, _rank_phrase


def _X(**kw):
    base = {"opp_pass_yds_allowed_rank": 30, "opp_pass_yds_allowed_pg": 260.0, "opp_pass_epa_allowed_rank": 28,
            "opp_games": 8, "opp_sos_adj_pass_rank": 29, "opp_sos_adj_pass_yds_allowed": 258.0,
            "opp_yds_per_dropback_rank": 16, "opp_yds_per_dropback_allowed": 6.4, "opp_sack_rate": 0.06,
            "implied_total": 26.0, "total_line": 50.5, "spread_team": -1.5, "team_proe": 0.05, "team_pass_rate": 0.62,
            "py_ewm": 270.0, "py_l3": 280.0, "usage_trend": 5.0, "games_career": 40, "games_prev_season": 17,
            "new_team": 0, "dome": 1}
    base.update(kw)
    return base


def test_factor_directions_flip_for_under():
    F = build_factors(_X(), 265.0, 262.0, 70.0, 250.5, None, None, None, True, "DAL", "PHI", True)
    d = {f["factor"]: f for f in F}
    assert d["opp_pass_def_rank"]["impact_over"] == +1
    assert d["implied_total"]["impact_over"] == +1
    assert d["team_proe"]["impact_over"] == +1
    assert "3rd-most" in d["opp_pass_def_rank"]["text"]
    assert d["projection"]["impact_over"] == 0


def test_rank_phrase():
    assert _rank_phrase(32, "x")[0].startswith("1st-most")
    assert _rank_phrase(1, "x")[0].startswith("1st-fewest")


def test_confidence_penalties():
    cand = {"edge": 0.05, "line": 250.5}
    full = confidence_score(_X(), cand, None, {"wind_mph": 5}, None, True, 4, "Over")
    rookie = confidence_score(_X(games_career=2, new_team=1), cand, None, {"wind_mph": 5}, None, True, 4, "Over")
    wk1 = confidence_score(_X(opp_games=0), cand, None, {"wind_mph": 5}, None, False, 4, "Over")
    assert full > rookie and full > wk1
    assert 0 <= rookie <= 100
    big = confidence_score(_X(), {"edge": 0.2, "line": 250.5}, None, {"wind_mph": 5}, None, True, 4, "Over")
    assert big < full
    moved = confidence_score(_X(), cand, 246.5, {"wind_mph": 5}, None, True, 4, "Over")
    assert moved < full
