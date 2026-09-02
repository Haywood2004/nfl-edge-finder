from nfl_edge.sources.odds_api import american, implied, no_vig_two_way


def test_american_conversion():
    assert american(1.91) == -110
    assert american(2.5) == 150
    assert american(1.5) == -200


def test_no_vig():
    a, b = no_vig_two_way(implied(1.91), implied(1.91))
    assert abs(a - 0.5) < 1e-9 and abs(a + b - 1) < 1e-9
    a, b = no_vig_two_way(implied(1.5), implied(2.65))
    assert a > b and abs(a + b - 1) < 1e-9


def test_nan_json_safe():
    import json, math
    from nfl_edge.db import _nan_to_none
    out = json.dumps(_nan_to_none({"a": float("nan"), "b": [1.0, math.inf, {"c": float("nan")}]}))
    assert "NaN" not in out and "Infinity" not in out
