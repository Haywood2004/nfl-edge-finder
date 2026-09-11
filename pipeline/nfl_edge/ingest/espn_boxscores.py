"""Same-day box scores from ESPN → raw_boxscores_espn, so cards can be graded the morning after a game instead of
waiting for nflverse's weekly stats file (which lags a day or more, and for a new season appears only after Week 1).

The grader prefers raw_weekly_stats (nflverse, the source of truth) and falls back to this table. Final scores are
also written into raw_games when missing, so moneyline cards grade too. Idempotent: upsert on (season, week, game_id,
player_id); ESPN athlete ids map to gsis ids through raw_rosters.espn_id, with a normalised name+team fallback.
"""
from __future__ import annotations
import datetime as dt
import re
import pandas as pd
from .. import db
from ..sources.espn import ESPN_ABBR, fetch_scoreboard, fetch_summary

ESPN_TZ = dt.timezone(dt.timedelta(hours=-4))   # ESPN dates are US/Eastern (EDT in season)


def _norm(s):
    s = re.sub(r"[^a-z ]", "", str(s).lower())
    s = re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", s)
    return " ".join(s.split())


def ingest_boxscores_espn(season: int | None = None, week: int | None = None, only_missing: bool = True) -> int:
    """Fetch box scores for every finished game of (season, week) — default: all weeks with a game finished ≥ 3h ago
    that has no nflverse stats yet."""
    now = dt.datetime.now(dt.timezone.utc)
    q = """SELECT g.game_id, g.season, g.week, g.kickoff_utc, g.home_team, g.away_team, g.home_score, g.away_score
           FROM raw_games g WHERE g.game_type='REG' AND g.kickoff_utc < :cut"""
    p = {"cut": now - dt.timedelta(hours=3)}
    if season:
        q += " AND g.season=:s"; p["s"] = season
    if week:
        q += " AND g.week=:w"; p["w"] = week
    if only_missing:
        q += """ AND NOT EXISTS (SELECT 1 FROM raw_weekly_stats s WHERE s.season=g.season AND s.week=g.week
                                 AND s.player_id IS NOT NULL LIMIT 1)"""
    games = db.read_sql(q + " ORDER BY g.kickoff_utc", p)
    if games.empty:
        print("[espn-box] no finished games without stats"); return 0
    rosters = db.read_sql("""SELECT DISTINCT ON (espn_id) espn_id, gsis_id, full_name, team FROM raw_rosters
                             WHERE espn_id IS NOT NULL AND gsis_id IS NOT NULL ORDER BY espn_id, season DESC""")
    by_espn = dict(zip(rosters.espn_id.astype(str), rosters.gsis_id))
    names = db.read_sql("SELECT DISTINCT ON (gsis_id) gsis_id, full_name, team FROM raw_rosters WHERE gsis_id IS NOT NULL ORDER BY gsis_id, season DESC")
    by_name = {(_norm(n), t): g for g, n, t in zip(names.gsis_id, names.full_name, names.team)}
    total, score_rows = 0, []
    with db.JobRun("ingest_boxscores_espn") as run:
        boards: dict[str, list[dict]] = {}
        for _, g in games.iterrows():
            date = g.kickoff_utc.astimezone(ESPN_TZ).strftime("%Y%m%d")
            if date not in boards:
                boards[date] = fetch_scoreboard(date)
            ev = next((e for e in boards[date] if e["home"] == g.home_team and e["away"] == g.away_team), None)
            if ev is None:
                print(f"[espn-box] {g.game_id}: not on ESPN scoreboard for {date}"); continue
            if ev["state"] != "post":
                print(f"[espn-box] {g.game_id}: ESPN state {ev['state']}, skipping"); continue
            box = fetch_summary(ev["espn_id"])
            if not box:
                print(f"[espn-box] {g.game_id}: no summary"); continue
            rows, unmapped = [], 0
            for pid, x in box["players"].items():
                gsis = by_espn.get(pid) or by_name.get((_norm(x["name"]), x["team"]))
                if not gsis:
                    unmapped += 1; continue
                rows.append({"season": int(g.season), "week": int(g.week), "game_id": g.game_id, "player_id": gsis,
                             "espn_id": pid, "player_name": x["name"], "team": x["team"],
                             "attempts": x["pass_att"], "completions": x["pass_cmp"], "passing_yards": x["pass_yds"],
                             "carries": x["rush_att"], "rushing_yards": x["rush_yds"],
                             "targets": x["tgt"], "receptions": x["rec"], "receiving_yards": x["rec_yds"],
                             "fetched_at": now})
            if rows:
                total += db.upsert(pd.DataFrame(rows), "raw_boxscores_espn", ["season", "week", "game_id", "player_id"])
            if pd.isna(g.home_score) and ev.get("home_score") is not None:
                score_rows.append({"game_id": g.game_id, "home_score": ev["home_score"], "away_score": ev["away_score"]})
            print(f"[espn-box] {g.game_id}: {len(rows)} players ({unmapped} unmapped), final {ev['away']} {ev['away_score']} @ {ev['home']} {ev['home_score']}")
        for s in score_rows:
            db.execute("UPDATE raw_games SET home_score=:h, away_score=:a WHERE game_id=:g AND home_score IS NULL", {"h": s["home_score"], "a": s["away_score"], "g": s["game_id"]})
        run.rows = total
    return total
