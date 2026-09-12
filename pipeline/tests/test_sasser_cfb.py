import datetime as dt
from pathlib import Path
from nfl_edge.ingest.sasser_cfb import parse_board, grade_pick

HTML = (Path(__file__).parent / "fixtures" / "sasser_cfb.html").read_text()


def test_parse_board():
    rows = parse_board(HTML, dt.datetime(2026, 9, 11))
    assert len(rows) == 2
    bc, ku = rows
    assert (bc["away_team"], bc["home_team"], bc["espn_id"]) == ("Rutgers", "Boston College", "401858214")
    assert bc["season"] == 2026 and bc["week"] == 2 and bc["game_date"] == dt.date(2026, 9, 11)
    assert (bc["proj_away_score"], bc["proj_home_score"]) == (26.5, 30.0)
    assert (bc["away_record"], bc["home_record"]) == ("0–1", "0–1")
    assert bc["open_line"] == "Boston College −3.5" and bc["current_line"] == "Boston College −3.0"
    assert bc["pick_text"] == "Boston College −3.0" and bc["pick_team"] == "Boston College" and bc["pick_line"] == -3.0 and bc["pick_is_home"] is True
    assert ku["pick_team"] == "Kansas" and ku["pick_line"] == 4.5 and ku["pick_is_home"] is True and ku["kickoff_text"] == "7:00 PM CT"


def test_grade_pick():
    # BC −3.0 at home, final BC 28 Rutgers 21 → covers
    assert grade_pick(-3.0, True, 28, 21)[0] == "win"
    assert grade_pick(-3.0, True, 24, 21)[0] == "push"
    assert grade_pick(-3.0, True, 21, 24)[0] == "loss"
    # Kansas +4.5 at home, loses by 7 → loss; loses by 3 → win
    assert grade_pick(4.5, True, 20, 27)[0] == "loss"
    assert grade_pick(4.5, True, 24, 27)[0] == "win"
    # away pick: Rutgers +3 loses by 2 → win
    r = grade_pick(3.0, False, 23, 21); assert r[0] == "win" and abs(r[1] - 100 / 110) < 1e-9
