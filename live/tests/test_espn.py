import json
from pathlib import Path
from live.espn import parse_scoreboard, parse_summary

FIX = Path(__file__).resolve().parents[1] / "fixtures"


def test_scoreboard():
    g = parse_scoreboard(json.loads((FIX / "espn_scoreboard_sample.json").read_text()))
    assert [x["state"] for x in g] == ["in", "pre", "post"]
    live = g[0]
    assert live["home"] == "ATL" and live["away"] == "WAS" and live["home_score"] == 24 and live["away_score"] == 17
    assert live["period"] == 3 and live["clock"] == "8:32" and live["possession"] == "WAS" and live["down"] == 2


def test_summary():
    s = parse_summary(json.loads((FIX / "espn_summary_sample.json").read_text()))
    assert s["teams"]["ATL"]["plays"] == 58 and s["teams"]["WAS"]["plays"] == 61
    assert s["teams"]["WAS"]["pass_att"] == 32 and s["teams"]["ATL"]["pass_att"] == 30   # both "21-30" and "17/32" forms
    p = s["players"]
    assert p["4360310"]["pass_att"] == 30 and p["4360310"]["pass_yds"] == 245.0
    assert p["4258173"]["tgt"] == 11 and p["4258173"]["rec_yds"] == 112.0 and p["4258173"]["team"] == "ATL"
    assert p["4429160"]["rush_att"] == 19 and p["4429160"]["rec"] == 4      # one athlete in two categories merges
    assert p["15818"]["team"] == "WAS"


def test_garbage_in_no_exception():
    assert parse_scoreboard({}) == []
    assert parse_summary({}) == {"teams": {}, "players": {}}
    assert parse_scoreboard({"events": [{"id": 1}]})[0]["state"] == "pre"
