"""Factors + confidence for skill-position prop cards (receiving yards, receptions, rushing yards).

Same contract as factors.py: each factor is {factor, value, impact_over, magnitude, text, source} and every
number points at the table it came from. The brief's coverage-matchup layer (receiver → likely CB) is not
available from free data yet, so that factor is emitted as `cb_matchup: unavailable` with a confidence
deduction rather than omitted silently.
"""
from __future__ import annotations
from .factors import TEAM_NAMES, _ord, _rank_phrase

RECEIVING = ("player_reception_yds", "player_receptions")


def build_skill_factors(X: dict, mean: float, used_mean: float, sd: float, line: float, open_line, weather, injury,
                        injury_data_available: bool, opponent: str, team: str, is_home: bool, market: str, position: str) -> list[dict]:
    F = []
    opp = TEAM_NAMES.get(opponent, opponent)
    g = lambda k: X.get(k)
    recv = market in RECEIVING
    pos = "RB" if position in ("RB", "FB") else position

    # 1. opponent, position-specific
    if recv:
        key = {"WR": ("opp_wr_yds_allowed_rank", "opp_wr_yds_allowed_pg", "receiving yards allowed to WRs per game"),
               "TE": ("opp_te_yds_allowed_rank", "opp_te_yds_allowed_pg", "receiving yards allowed to TEs per game"),
               "RB": ("opp_rb_rec_yds_allowed_rank", "opp_rb_rec_yds_allowed_pg", "receiving yards allowed to RBs per game")}[pos]
    else:
        key = ("opp_rush_yds_allowed_rank", "opp_rush_yds_allowed_pg", "rushing yards allowed per game")
    rk_k, val_k, what = key
    if g(rk_k) is not None:
        rk = int(g(rk_k))
        txt, imp = _rank_phrase(rk, what)
        basis = "last season, shrunk toward league avg" if (g("opp_games") or 0) == 0 else f"{int(g('opp_games'))} games this season"
        sentence = f"{opp} allow the {txt}" if imp != 0 else f"{opp} rank {_ord(rk)} in {what}"
        F.append({"factor": "opp_pos_def_rank", "value": rk, "impact_over": imp, "magnitude": abs(rk - 16.5) / 15.5,
                  "text": f"{sentence} ({g(val_k):.1f}/g) — {basis}",
                  "source": {"table": "feat_team_defense", "team": opponent, "key": rk_k.replace("opp_", "")}})
    if recv and g("opp_pass_epa_allowed_rank") is not None:
        rk = int(g("opp_pass_epa_allowed_rank"))
        if rk >= 25 or rk <= 8:
            txt, imp = _rank_phrase(rk, "EPA per dropback allowed")
            F.append({"factor": "opp_pass_def_epa", "value": rk, "impact_over": imp, "magnitude": abs(rk - 16.5) / 15.5 * 0.6,
                      "text": f"{opp} pass defense: {txt}", "source": {"table": "feat_team_defense", "team": opponent, "key": "pass_epa_allowed_rank"}})
    if not recv and g("opp_rush_epa_allowed_rank") is not None:
        rk = int(g("opp_rush_epa_allowed_rank"))
        if rk >= 25 or rk <= 8:
            txt, imp = _rank_phrase(rk, "EPA per rush allowed")
            F.append({"factor": "opp_run_def_epa", "value": rk, "impact_over": imp, "magnitude": abs(rk - 16.5) / 15.5 * 0.6,
                      "text": f"{opp} run defense: {txt}", "source": {"table": "feat_team_defense", "team": opponent, "key": "rush_epa_allowed_rank"}})
    if recv and pos in ("WR", "TE"):
        F.append({"factor": "cb_matchup", "value": None, "impact_over": 0, "magnitude": 0.1,
                  "text": "Coverage matchup (likely defender) unavailable — no free per-defender coverage source yet; confidence reduced",
                  "source": {"table": "n/a"}})

    # 2. role / usage
    if recv:
        share, rank, tgt = g("tgt_share_ewm"), g("tgt_rank_team"), g("tgt_ewm")
        if share is not None and tgt is not None:
            F.append({"factor": "target_role", "value": round(share, 3), "impact_over": (1 if share >= 0.22 else -1 if share <= 0.12 else 0),
                      "magnitude": min(abs(share - 0.17) / 0.12, 1) * 0.7,
                      "text": f"{share:.0%} target share (recent-weighted), {tgt:.1f} targets/game — {_ord(int(rank)) if rank else '?'} target on the team",
                      "source": {"table": "raw_weekly_stats", "key": "targets"}})
        if g("adot_ewm") is not None and market == "player_reception_yds":
            adot = g("adot_ewm")
            if adot >= 12 or adot <= 6:
                F.append({"factor": "adot", "value": round(adot, 1), "impact_over": (1 if adot >= 12 else -1), "magnitude": 0.3,
                          "text": f"Average depth of target {adot:.1f} yds — {'downfield role, high variance' if adot >= 12 else 'short-area role, volume-dependent'}",
                          "source": {"table": "raw_weekly_stats", "key": "receiving_air_yards"}})
        if g("catch_rate_ewm") is not None and market == "player_receptions":
            F.append({"factor": "catch_rate", "value": round(g("catch_rate_ewm"), 3), "impact_over": (1 if g("catch_rate_ewm") >= 0.72 else -1 if g("catch_rate_ewm") <= 0.55 else 0),
                      "magnitude": 0.3, "text": f"Catch rate {g('catch_rate_ewm'):.0%} (recent-weighted)",
                      "source": {"table": "raw_weekly_stats", "key": "receptions"}})
    else:
        share, rank, car = g("carry_share_ewm"), g("car_rank_team"), g("car_ewm")
        if share is not None and car is not None:
            F.append({"factor": "carry_role", "value": round(share, 3), "impact_over": (1 if share >= 0.55 else -1 if share <= 0.3 else 0),
                      "magnitude": min(abs(share - 0.42) / 0.3, 1) * 0.7,
                      "text": f"{share:.0%} of team carries (recent-weighted), {car:.1f} carries/game — {_ord(int(rank)) if rank else '?'} back on the team",
                      "source": {"table": "raw_weekly_stats", "key": "carries"}})
        if g("ypc_ewm") is not None:
            F.append({"factor": "ypc", "value": round(g("ypc_ewm"), 2), "impact_over": (1 if g("ypc_ewm") >= 4.8 else -1 if g("ypc_ewm") <= 3.7 else 0),
                      "magnitude": 0.3, "text": f"{g('ypc_ewm'):.2f} yards per carry (recent-weighted)",
                      "source": {"table": "raw_weekly_stats", "key": "rushing_yards"}})

    # 3. form vs line
    ewm_key = {"player_reception_yds": "recy_ewm", "player_receptions": "rec_ewm", "player_rush_yds": "ruy_ewm"}[market]
    l3_key = ewm_key.replace("_ewm", "_l3")
    ewm, l3 = g(ewm_key), g(l3_key)
    if ewm is not None:
        diff = ewm - line
        scale = 1.0 if market == "player_receptions" else 12.0
        F.append({"factor": "player_form", "value": round(ewm, 1), "impact_over": (1 if diff > scale * 0.6 else -1 if diff < -scale * 0.6 else 0),
                  "magnitude": min(abs(diff) / (scale * 3), 1) * 0.5,
                  "text": f"Recent-weighted average {ewm:.1f} (last 3: {l3:.1f}) vs line {line}",
                  "source": {"table": "raw_weekly_stats", "key": ewm_key}})
    trend = g("usage_trend") if recv else g("carry_trend")
    if trend is not None and abs(trend) >= (2 if recv else 4):
        F.append({"factor": "usage_trend", "value": round(trend, 1), "impact_over": (1 if trend > 0 else -1), "magnitude": min(abs(trend) / 6, 1) * 0.4,
                  "text": f"Last-3 {'targets' if recv else 'carries'} {trend:+.1f} vs last-10 — {'rising' if trend > 0 else 'falling'} usage",
                  "source": {"table": "raw_weekly_stats", "key": "targets" if recv else "carries"}})

    # 4. game environment
    it, tl, sp = g("implied_total"), g("total_line"), g("spread_team")
    if it is not None:
        imp = +1 if it >= 24.5 else (-1 if it <= 19.5 else 0)
        F.append({"factor": "implied_total", "value": round(it, 2), "impact_over": imp, "magnitude": abs(it - 22) / 8,
                  "text": f"Implied team total {it:.2f} (game total {tl}, {'favored by' if sp < 0 else 'underdog by'} {abs(sp):g})",
                  "source": {"table": "raw_games", "key": "spread_line/total_line"}})
    if sp is not None:
        if recv and sp >= 6.5:
            F.append({"factor": "trailing_script", "value": sp, "impact_over": +1, "magnitude": min(sp / 14, 1) * 0.5,
                      "text": f"{abs(sp):g}-point underdog — trailing script raises pass volume", "source": {"table": "raw_games", "key": "spread_line"}})
        if not recv and sp <= -6.5:
            F.append({"factor": "leading_script", "value": sp, "impact_over": +1, "magnitude": min(-sp / 14, 1) * 0.5,
                      "text": f"{abs(sp):g}-point favorite — leading script raises carries", "source": {"table": "raw_games", "key": "spread_line"}})
        if not recv and sp >= 6.5:
            F.append({"factor": "trailing_script", "value": sp, "impact_over": -1, "magnitude": min(sp / 14, 1) * 0.4,
                      "text": f"{abs(sp):g}-point underdog — trailing script cuts carries", "source": {"table": "raw_games", "key": "spread_line"}})
    proe = g("team_proe")
    if proe is not None and abs(proe) >= 0.03:
        F.append({"factor": "team_proe", "value": round(proe, 3), "impact_over": (1 if (proe > 0) == recv else -1),
                  "magnitude": min(abs(proe) / 0.08, 1) * 0.5,
                  "text": f"{TEAM_NAMES.get(team, team)} pass rate over expectation {proe:+.1%}",
                  "source": {"table": "feat_team_offense", "team": team, "key": "proe"}})

    # 5. injuries / redistribution (teammates out → this player's share)
    if g("injury_report_seen") == 1:
        tso = g("target_share_out") or 0
        if recv and tso >= 0.08:
            F.append({"factor": "injury_redistribution", "value": round(tso, 3), "impact_over": +1, "magnitude": min(tso / 0.25, 1) * 0.6,
                      "text": f"Teammates ruled out held {tso:.0%} of this team's prior targets{' (top target out)' if g('wr1_out') == 1 else ''} — targets redistribute",
                      "source": {"table": "raw_injuries", "team": team, "key": "report_status"}})
        if (g("ol_out") or 0) >= 2:
            F.append({"factor": "ol_injuries", "value": int(g("ol_out")), "impact_over": -1, "magnitude": 0.3,
                      "text": f"{int(g('ol_out'))} offensive linemen ruled out", "source": {"table": "raw_injuries", "team": team, "key": "position"}})
        if recv and (g("opp_db_out") or 0) >= 2:
            F.append({"factor": "opp_secondary_injuries", "value": int(g("opp_db_out")), "impact_over": +1, "magnitude": 0.4,
                      "text": f"{opp} have {int(g('opp_db_out'))} defensive backs ruled out", "source": {"table": "raw_injuries", "team": opponent, "key": "position"}})
        if not recv and (g("opp_front_out") or 0) >= 2:
            F.append({"factor": "opp_front_injuries", "value": int(g("opp_front_out")), "impact_over": +1, "magnitude": 0.4,
                      "text": f"{opp} have {int(g('opp_front_out'))} front-seven players ruled out", "source": {"table": "raw_injuries", "team": opponent, "key": "position"}})
    else:
        F.append({"factor": "injury_report", "value": None, "impact_over": 0, "magnitude": 0.2,
                  "text": "Official injury report not yet published for this week", "source": {"table": "raw_injuries"}})
    if injury and injury.get("report_status") in ("Questionable", "Doubtful", "Out"):
        st = injury["report_status"]
        F.append({"factor": "player_injury_status", "value": st, "impact_over": -1 if st in ("Out", "Doubtful") else 0, "magnitude": 0.8 if st == "Out" else 0.4,
                  "text": f"Listed {st}{(' — ' + injury['report_primary_injury']) if injury.get('report_primary_injury') else ''}",
                  "source": {"table": "raw_injuries", "key": "report_status"}})

    # 6. sample / regime / weather / line move
    if (g("games_career") or 0) < 8:
        F.append({"factor": "small_sample", "value": g("games_career"), "impact_over": 0, "magnitude": 0.5,
                  "text": f"Only {int(g('games_career') or 0)} active games — projection leans on priors", "source": {"table": "raw_weekly_stats", "key": "games"}})
    if g("new_team") == 1:
        F.append({"factor": "new_team", "value": 1, "impact_over": 0, "magnitude": 0.45, "text": "First game with a new team", "source": {"table": "raw_rosters", "key": "team"}})
    if g("new_hc") == 1:
        F.append({"factor": "new_coaching_staff", "value": 1, "impact_over": 0, "magnitude": 0.3,
                  "text": "New head coach this season — last year's usage patterns may not carry over", "source": {"table": "raw_games", "key": "home_coach/away_coach"}})
    if g("dome") == 1:
        F.append({"factor": "weather", "value": "dome", "impact_over": 0, "magnitude": 0.05, "text": "Indoors (dome)", "source": {"table": "raw_games", "key": "roof"}})
    elif weather and weather.get("wind_mph") is not None:
        w = float(weather["wind_mph"])
        if recv and w >= 12:
            F.append({"factor": "weather", "value": round(w, 1), "impact_over": -1, "magnitude": min(w / 25, 1) * 0.5,
                      "text": f"{w:.0f} mph wind forecast at kickoff, outdoors", "source": {"table": "raw_weather", "key": "wind_mph"}})
        elif not recv and w >= 15:
            F.append({"factor": "weather", "value": round(w, 1), "impact_over": +1, "magnitude": 0.3,
                      "text": f"{w:.0f} mph wind — teams lean on the run", "source": {"table": "raw_weather", "key": "wind_mph"}})
    if open_line is not None and abs(line - open_line) >= (0.5 if market == "player_receptions" else 2):
        moved_up = line > open_line
        F.append({"factor": "line_move", "value": round(line - open_line, 1), "impact_over": (-1 if moved_up else +1), "magnitude": 0.35,
                  "text": f"Line moved {open_line:g} → {line:g} since open ({'toward the over' if moved_up else 'toward the under'})",
                  "source": {"table": "odds_lines", "key": "line"}})
    F.append({"factor": "projection", "value": round(used_mean, 1), "impact_over": 0, "magnitude": 0.0,
              "text": f"Model {mean:.1f} → market-anchored {used_mean:.1f} (sd {sd:.1f}) vs consensus line {line:g}",
              "source": {"table": "projections", "key": "mean"}})
    return [x for x in F if x is not None]


def skill_confidence(X: dict, cand: dict, open_line, weather, injury, injury_data_available: bool,
                     n_books: int, side: str, market: str) -> int:
    c = 70.0
    g = lambda k: X.get(k)
    career = g("games_career") or 0
    if career < 4:
        c -= 22
    elif career < 10:
        c -= 12
    elif career < 20:
        c -= 5
    if (g("games_prev_season") or 0) < 6:
        c -= 5
    if g("new_team") == 1:
        c -= 10
    if g("new_hc") == 1:
        c -= 3
    if (g("opp_games") or 0) == 0:
        c -= 8
    elif (g("opp_games") or 0) < 4:
        c -= 4
    if not injury_data_available:
        c -= 6
    elif injury and injury.get("report_status") in ("Questionable", "Doubtful"):
        c -= 14
    elif injury and injury.get("report_status") == "Out":
        c -= 45
    if market in RECEIVING:
        c -= 5   # coverage-matchup layer unavailable (brief §4.2)
        if (g("tgt_ewm") or 0) < 4:
            c -= 6   # low-volume receivers: outcomes are lumpy
    if g("dome") != 1 and not (weather and weather.get("wind_mph") is not None):
        c -= 3
    if n_books < 3:
        c -= 4
    if open_line is not None:
        moved = cand["line"] - open_line
        against = moved > 0 if side == "Over" else moved < 0
        thresh = 0.5 if market == "player_receptions" else 3
        if against and abs(moved) >= thresh:
            c -= 8
    if cand["edge"] > 0.15:
        c -= 12
    elif cand["edge"] > 0.10:
        c -= 6
    return int(max(0, min(100, round(c))))
