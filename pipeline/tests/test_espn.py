from nfl_edge.sources.espn import parse_injuries


def test_parse_espn_payload():
    payload = {"injuries": [{"displayName": "Arizona Cardinals", "injuries": [
        {"status": "Injured Reserve", "date": "2026-09-01T19:38Z",
         "athlete": {"id": 4870808, "displayName": "Jeremiyah Love", "position": {"abbreviation": "RB"},
                     "team": {"abbreviation": "WSH"}},
         "details": {"type": "Ankle"}},
        {"status": "Questionable", "athlete": {"id": "1", "displayName": "X Y", "position": {"abbreviation": "WR"},
                                                "team": {"abbreviation": "LAR"}}}]}]}
    rows = parse_injuries(payload)
    assert rows[0]["report_status"] == "Out" and rows[0]["team"] == "WAS" and rows[0]["espn_id"] == "4870808"
    assert rows[1]["report_status"] == "Questionable" and rows[1]["team"] == "LA"
