"""Human-verifiable factors and the confidence score for passing-yards cards.

Each factor: {factor, value, impact_over (+1/-1/0), magnitude (0..1 for ranking), text, source}
`source` tells the UI where the number can be checked (table + key).
"""
from __future__ import annotations
import numpy as np

TEAM_NAMES = {
    "ARI": "Cardinals", "ATL": "Falcons", "BAL": "Ravens", "BUF": "Bills", "CAR": "Panthers", "CHI": "Bears",
    "CIN": "Bengals", "CLE": "Browns", "DAL": "Cowboys", "DEN": "Broncos", "DET": "Lions", "GB": "Packers",
    "HOU": "Texans", "IND": "Colts", "JAX": "Jaguars", "KC": "Chiefs", "LV": "Raiders", "LAC": "Chargers",
    "LA": "Rams", "MIA": "Dolphins", "MIN": "Vikings", "NE": "Patriots", "NO": "Saints", "NYG": "Giants",
    "NYJ": "Jets", "PHI": "Eagles", "PIT": "Steelers", "SF": "49ers", "SEA": "Seahawks", "TB": "Buccaneers",
    "TEN": "Titans", "WAS": "Commanders",
}


def _ord(n: int) -> str:
    n = int(n)
    suf = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"


def _rank_phrase(rank, what) -> tuple[str, int]:
    """rank 1 = stingiest. Returns (text, impact_over)."""
    rank = int(rank)
    if rank >= 25:
        return f"{_ord(33 - rank)}-most {what}", +1
    if rank <= 8:
        return f"{_ord(rank)}-fewest {what}", -1
    return f"{_ord(rank)} in {what}", 0


def build_factors(X: dict, mean: float, used_mean: float, sd: float, line: float, open_line, weather, injury,
                  injury_data_available: bool, opponent: str, team: str, is_home: bool) -> list[dict]:
    F = []
    opp = TEAM_NAMES.get(opponent, opponent)
    g = lambda k: X.get(k)

    # 1. opponent pass defense (raw + SOS-adjusted + EPA)
    if g("opp_pass_yds_allowed_rank") is not None:
        rk = int(g("opp_pass_yds_allowed_rank"))
        txt, imp = _rank_phrase(rk, "passing yards allowed per game")
        epa_rk = g("opp_pass_epa_allowed_rank")
        epa_txt = f", {_ord(int(epa_rk))} in EPA/dropback allowed" if epa_rk is not None else ""
        basis = "2025 season, shrunk toward league avg" if (g("opp_games") or 0) == 0 else f"{int(g('opp_games'))} games this season"
        F.append({"factor": "opp_pass_def_rank", "value": rk, "impact_over": imp,
                  "magnitude": abs(rk - 16.5) / 15.5,
                  "text": f"{opp} allow the {txt} ({g('opp_pass_yds_allowed_pg'):.1f}/g{epa_txt}) — {basis}",
                  "source": {"table": "feat_team_defense", "team": opponent, "key": "pass_yds_allowed_rank"}})
        srk = g("opp_sos_adj_pass_rank")
        if srk is not None and abs(int(srk) - rk) >= 5:
            s_txt, s_imp = _rank_phrase(int(srk), "schedule-adjusted passing yards allowed")
            F.append({"factor": "opp_pass_def_sos", "value": int(srk), "impact_over": s_imp,
                      "magnitude": abs(int(srk) - 16.5) / 15.5 * 0.6,
                      "text": f"Schedule-adjusted, {opp} rank {_ord(int(srk))} ({g('opp_sos_adj_pass_yds_allowed'):.1f}/g) — "
                              f"{'tougher' if int(srk) < rk else 'softer'} than the raw number suggests",
                      "source": {"table": "feat_team_defense", "team": opponent, "key": "sos_adj_pass_rank"}})
    if g("opp_yds_per_dropback_rank") is not None:
        rk = int(g("opp_yds_per_dropback_rank"))
        if rk >= 25 or rk <= 8:
            txt, imp = _rank_phrase(rk, "yards per dropback allowed")
            F.append({"factor": "opp_yds_per_dropback", "value": round(g("opp_yds_per_dropback_allowed"), 2),
                      "impact_over": imp, "magnitude": abs(rk - 16.5) / 15.5 * 0.7,
                      "text": f"{opp} allow {g('opp_yds_per_dropback_allowed'):.2f} yds/dropback ({txt})",
                      "source": {"table": "feat_team_defense", "team": opponent, "key": "yds_per_dropback_rank"}})
    if g("opp_sack_rate") is not None and g("opp_sack_rate") >= 0.085:
        F.append({"factor": "opp_pass_rush", "value": round(g("opp_sack_rate"), 3), "impact_over": -1, "magnitude": 0.4,
                  "text": f"{opp} sack rate {g('opp_sack_rate'):.1%} (high) — drives, not just yards, end early",
                  "source": {"table": "feat_team_defense", "team": opponent, "key": "sack_rate"}})

    # 2. game environment
    it, tl, sp = g("implied_total"), g("total_line"), g("spread_team")
    if it is not None:
        imp = +1 if it >= 24.5 else (-1 if it <= 19.5 else 0)
        F.append({"factor": "implied_total", "value": round(it, 2), "impact_over": imp, "magnitude": abs(it - 22) / 8,
                  "text": f"Implied team total {it:.2f} (game total {tl}, {'favored by' if sp < 0 else 'underdog by'} {abs(sp):g})",
                  "source": {"table": "raw_games", "key": "spread_line/total_line"}})
    if sp is not None and sp >= 6.5:
        F.append({"factor": "trailing_script", "value": sp, "impact_over": +1, "magnitude": min(sp / 14, 1) * 0.5,
                  "text": f"{abs(sp):g}-point underdog — likely trailing game script raises pass volume",
                  "source": {"table": "raw_games", "key": "spread_line"}})
    if sp is not None and sp <= -9.5:
        F.append({"factor": "leading_script", "value": sp, "impact_over": -1, "magnitude": min(-sp / 14, 1) * 0.5,
                  "text": f"{abs(sp):g}-point favorite — blowout risk caps second-half passing",
                  "source": {"table": "raw_games", "key": "spread_line"}})

    # 3. team pass tendency
    proe, pr = g("team_proe"), g("team_pass_rate")
    if proe is not None:
        imp = +1 if proe >= 0.03 else (-1 if proe <= -0.03 else 0)
        F.append({"factor": "team_proe", "value": round(proe, 3), "impact_over": imp, "magnitude": min(abs(proe) / 0.08, 1) * 0.6,
                  "text": f"{TEAM_NAMES.get(team, team)} pass rate over expectation {proe:+.1%} (pass rate {pr:.1%})",
                  "source": {"table": "feat_team_offense", "team": team, "key": "proe"}})

    # 4. player form vs line
    ewm, l3, trend = g("py_ewm"), g("py_l3"), g("usage_trend")
    if ewm is not None:
        diff = ewm - line
        F.append({"factor": "player_form", "value": round(ewm, 1), "impact_over": (1 if diff > 10 else -1 if diff < -10 else 0),
                  "magnitude": min(abs(diff) / 40, 1) * 0.5,
                  "text": f"Recent-weighted average {ewm:.1f} yds (last 3: {l3:.1f}) vs line {line}",
                  "source": {"table": "raw_weekly_stats", "key": "passing_yards"}})
    if trend is not None and abs(trend) >= 25:
        F.append({"factor": "usage_trend", "value": round(trend, 1), "impact_over": (1 if trend > 0 else -1),
                  "magnitude": min(abs(trend) / 60, 1) * 0.4,
                  "text": f"Last-3 average is {trend:+.0f} yds vs last-10 — {'rising' if trend > 0 else 'falling'} usage",
                  "source": {"table": "raw_weekly_stats", "key": "passing_yards"}})

    # 5. sample / role risk
    if (g("games_career") or 0) < 8:
        F.append({"factor": "small_sample", "value": g("games_career"), "impact_over": 0, "magnitude": 0.5,
                  "text": f"Only {int(g('games_career') or 0)} career starts — projection leans on priors",
                  "source": {"table": "raw_weekly_stats", "key": "games"}})
    if g("new_team") == 1:
        F.append({"factor": "new_team", "value": 1, "impact_over": 0, "magnitude": 0.45,
                  "text": "First game with a new team — history reflects a different offense",
                  "source": {"table": "raw_rosters", "key": "team"}})
    if (g("opp_games") or 0) == 0:
        F.append({"factor": "early_season", "value": 0, "impact_over": 0, "magnitude": 0.3,
                  "text": "No current-season defensive data yet; opponent profile is last season's, shrunk 50% toward league average",
                  "source": {"table": "feat_team_defense", "team": opponent, "key": "games"}})

    # 5b. context v2: coaching regime, own-side injuries, opponent-side injuries
    if g("new_hc") == 1:
        F.append({"factor": "new_coaching_staff", "value": 1, "impact_over": 0, "magnitude": 0.35,
                  "text": "New head coach this season — last year's pass rate, pace and formation tendencies were replaced "
                          "with league-average priors until this staff has a sample",
                  "source": {"table": "raw_games", "key": "home_coach/away_coach"}})
    if g("injury_report_seen") == 1:
        tso = g("target_share_out") or 0
        if g("wr1_out") == 1:
            F.append({"factor": "injury_redistribution", "value": round(tso, 3), "impact_over": -1, "magnitude": min(tso / 0.25, 1) * 0.6,
                      "text": f"Top target is OUT — receivers ruled out held {tso:.0%} of this team's prior targets; "
                              "passing volume historically drops when the WR1 is missing",
                      "source": {"table": "raw_injuries", "team": team, "key": "report_status"}})
        elif tso >= 0.08:
            F.append({"factor": "injury_redistribution", "value": round(tso, 3), "impact_over": -1, "magnitude": min(tso / 0.25, 1) * 0.4,
                      "text": f"Receivers ruled out held {tso:.0%} of this team's prior targets ({int(g('skill_out') or 0)} skill players out)",
                      "source": {"table": "raw_injuries", "team": team, "key": "report_status"}})
        if (g("ol_out") or 0) >= 2:
            F.append({"factor": "ol_injuries", "value": int(g("ol_out")), "impact_over": -1, "magnitude": 0.3,
                      "text": f"{int(g('ol_out'))} offensive linemen ruled out — pressure and sack risk up, depth of target down",
                      "source": {"table": "raw_injuries", "team": team, "key": "position"}})
        if (g("opp_db_out") or 0) >= 2:
            F.append({"factor": "opp_secondary_injuries", "value": int(g("opp_db_out")), "impact_over": +1, "magnitude": min(g("opp_db_out") / 3, 1) * 0.5,
                      "text": f"{TEAM_NAMES.get(opponent, opponent)} have {int(g('opp_db_out'))} defensive backs ruled out",
                      "source": {"table": "raw_injuries", "team": opponent, "key": "position"}})
        if (g("opp_front_out") or 0) >= 2:
            F.append({"factor": "opp_front_injuries", "value": int(g("opp_front_out")), "impact_over": +1, "magnitude": 0.25,
                      "text": f"{TEAM_NAMES.get(opponent, opponent)} have {int(g('opp_front_out'))} front-seven players ruled out — less pass rush",
                      "source": {"table": "raw_injuries", "team": opponent, "key": "position"}})

    # 6. weather
    dome = g("dome") == 1
    if dome:
        F.append({"factor": "weather", "value": "dome", "impact_over": 0, "magnitude": 0.05, "text": "Indoors (dome)",
                  "source": {"table": "raw_games", "key": "roof"}})
    elif weather and weather.get("wind_mph") is not None:
        w = float(weather["wind_mph"])
        imp = -1 if w >= 15 else 0
        F.append({"factor": "weather", "value": round(w, 1), "impact_over": imp, "magnitude": min(w / 25, 1) * (0.6 if w >= 15 else 0.1),
                  "text": f"{w:.0f} mph wind forecast at kickoff, {weather.get('temp_f') or 0:.0f}°F"
                          + (f", {weather.get('precip_prob'):.0f}% precip" if weather.get("precip_prob") is not None else ""),
                  "source": {"table": "raw_weather", "key": "wind_mph"}})
    else:
        F.append({"factor": "weather", "value": None, "impact_over": 0, "magnitude": 0.15,
                  "text": "Outdoor game — weather forecast unavailable", "source": {"table": "raw_weather", "key": "wind_mph"}})

    # 7. injuries
    if not injury_data_available:
        F.append({"factor": "injury_report", "value": None, "impact_over": 0, "magnitude": 0.2,
                  "text": "Official injury report not yet published for this week", "source": {"table": "raw_injuries"}})
    elif injury:
        st = injury.get("report_status") or injury.get("practice_status")
        if st:
            F.append({"factor": "player_injury_status", "value": st, "impact_over": -1 if st in ("Out", "Doubtful") else 0,
                      "magnitude": 0.6 if st in ("Out", "Doubtful", "Questionable") else 0.1,
                      "text": f"Listed {st} ({injury.get('report_primary_injury') or 'undisclosed'})",
                      "source": {"table": "raw_injuries", "key": "report_status"}})

    # 8. line movement
    if open_line is not None and abs(open_line - line) >= 1:
        moved_up = line > open_line
        F.append({"factor": "line_move", "value": round(line - open_line, 1), "impact_over": (-1 if moved_up else +1),
                  "magnitude": min(abs(line - open_line) / 10, 1) * 0.5,
                  "text": f"Line moved {open_line:g} → {line:g} since open ({'toward the over' if moved_up else 'toward the under'})",
                  "source": {"table": "odds_lines", "key": "line"}})

    # 9. projection summary (always present, neutral)
    F.append({"factor": "projection", "value": round(used_mean, 1), "impact_over": 0, "magnitude": 0.0,
              "text": f"Model {mean:.1f} → market-anchored {used_mean:.1f} (P25 {used_mean - 0.674 * sd:.0f} · P75 {used_mean + 0.674 * sd:.0f}) vs consensus line {line:g}",
              "source": {"table": "projections", "key": "mean"}})
    return F


def confidence_score(X: dict, cand: dict, open_line, weather, injury, injury_data_available: bool,
                     n_books: int, side: str) -> int:
    c = 72.0
    g = lambda k: X.get(k)
    career = g("games_career") or 0
    if career < 4:
        c -= 22
    elif career < 10:
        c -= 12
    elif career < 20:
        c -= 5
    if (g("games_prev_season") or 0) < 6:
        c -= 6
    if g("new_team") == 1:
        c -= 10
    if (g("opp_games") or 0) == 0:
        c -= 10         # week 1: opponent profile is last season's; model over-predicts early season historically
    elif (g("opp_games") or 0) < 4:
        c -= 5
    if not injury_data_available:
        c -= 6
    elif injury and injury.get("report_status") in ("Questionable", "Doubtful"):
        c -= 12
    elif injury and injury.get("report_status") == "Out":
        c -= 40
    if g("dome") != 1 and not (weather and weather.get("wind_mph") is not None):
        c -= 4
    if n_books < 3:
        c -= 4
    if open_line is not None:
        moved = cand["line"] - open_line
        against = moved > 0 if side == "Over" else moved < 0
        if against and abs(moved) >= 2:
            c -= min(10, 2.5 * abs(moved))
    # sanity: very large disagreements with the market are more often model error than edge
    if cand["edge"] > 0.15:
        c -= 12
    elif cand["edge"] > 0.10:
        c -= 5
    return int(max(0, min(100, round(c))))
