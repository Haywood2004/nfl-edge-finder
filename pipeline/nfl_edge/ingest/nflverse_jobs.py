"""Idempotent nflverse ingest jobs. Each writes raw_* tables via upsert on natural keys."""
from __future__ import annotations
import datetime as dt
import pandas as pd
from zoneinfo import ZoneInfo
from .. import db
from ..config import FIRST_TRAIN_SEASON
from ..sources import nflverse
from ..teams import norm

ET = ZoneInfo("America/New_York")


def current_season(today: dt.date | None = None) -> int:
    today = today or dt.date.today()
    return today.year if today.month >= 3 else today.year - 1


def seasons_through_current(first: int = FIRST_TRAIN_SEASON) -> list[int]:
    return list(range(first, current_season() + 1))


# ---------------------------------------------------------------- schedule
GAME_COLS = ["game_id", "season", "game_type", "week", "gameday", "weekday", "gametime", "away_team", "home_team",
             "away_score", "home_score", "result", "total", "overtime", "away_rest", "home_rest", "away_moneyline",
             "home_moneyline", "spread_line", "total_line", "div_game", "roof", "surface", "temp", "wind",
             "away_qb_id", "home_qb_id", "away_qb_name", "home_qb_name", "stadium_id", "stadium"]


def ingest_schedule(seasons: list[int] | None = None) -> int:
    with db.JobRun("ingest_schedule") as run:
        g = nflverse.load("schedules")
        seasons = seasons or seasons_through_current()
        g = g[g.season.isin(seasons)][GAME_COLS].copy()
        for c in ("away_team", "home_team"):
            g[c] = g[c].map(norm)
        # kickoff in UTC from ET gameday + gametime (nflverse stores ET)
        def kick(r):
            if pd.isna(r.gameday):
                return None
            t = r.gametime if isinstance(r.gametime, str) else "13:00"
            return dt.datetime.fromisoformat(f"{r.gameday}T{t}:00").replace(tzinfo=ET).astimezone(dt.timezone.utc)
        g["kickoff_utc"] = g.apply(kick, axis=1)
        run.rows = db.upsert(g, "raw_games", ["game_id"])
        # stadiums reference
        from ..teams import STADIUMS
        st = pd.DataFrame([{"team": t, "stadium": s[0], "lat": s[1], "lon": s[2], "roof": s[3], "tz": s[4]}
                           for t, s in STADIUMS.items()])
        db.upsert(st, "stadiums", ["team"])
        return run.rows


# ---------------------------------------------------------------- pbp
PBP_COLS = ["play_id", "game_id", "season", "week", "season_type", "posteam", "defteam", "home_team", "away_team",
            "qtr", "down", "ydstogo", "yardline_100", "game_seconds_remaining", "play_type", "pass", "rush",
            "qb_dropback", "qb_scramble", "sack", "complete_pass", "incomplete_pass", "interception", "yards_gained",
            "air_yards", "yards_after_catch", "passing_yards", "rushing_yards", "receiving_yards", "epa", "wpa",
            "cpoe", "success", "xpass", "pass_oe", "touchdown", "pass_touchdown", "rush_touchdown",
            "passer_player_id", "passer_player_name", "receiver_player_id", "receiver_player_name",
            "rusher_player_id", "rusher_player_name", "pass_location", "pass_length", "run_location",
            "shotgun", "no_huddle", "score_differential"]


def ingest_pbp(seasons: list[int] | None = None) -> int:
    seasons = seasons or seasons_through_current()
    total = 0
    with db.JobRun("ingest_pbp") as run:
        for s in seasons:
            try:
                p = nflverse.load("pbp", s, columns=PBP_COLS)
            except nflverse.NotAvailable as e:
                print(f"[pbp] {e}")
                run.detail[str(s)] = "not available"
                continue
            p = p[p.posteam.notna()]  # drop timeouts/end-of-quarter rows
            for c in ("posteam", "defteam", "home_team", "away_team"):
                p[c] = p[c].map(lambda v: norm(v) if isinstance(v, str) else v)
            int_cols = ["qtr", "down", "ydstogo", "yardline_100", "game_seconds_remaining", "pass", "rush",
                        "qb_dropback", "qb_scramble", "sack", "complete_pass", "incomplete_pass", "interception",
                        "yards_gained", "touchdown", "pass_touchdown", "rush_touchdown", "shotgun", "no_huddle",
                        "score_differential"]
            for c in int_cols:
                p[c] = p[c].astype("Int64")
            n = db.upsert(p, "raw_pbp", ["game_id", "play_id"], chunk=10000, update=False)
            print(f"[pbp] {s}: {n} plays")
            run.detail[str(s)] = n
            total += n
        run.rows = total
    return total


# ---------------------------------------------------------------- weekly stats
WS_COLS = ["player_id", "player_display_name", "position", "season", "week", "season_type", "team", "opponent_team",
           "completions", "attempts", "passing_yards", "passing_tds", "passing_interceptions", "sacks_suffered",
           "passing_air_yards", "passing_yards_after_catch", "passing_epa", "passing_cpoe", "carries", "rushing_yards",
           "rushing_tds", "receptions", "targets", "receiving_yards", "receiving_tds", "receiving_air_yards",
           "receiving_yards_after_catch", "target_share", "air_yards_share", "wopr", "fantasy_points_ppr"]


def ingest_weekly_stats(seasons: list[int] | None = None) -> int:
    seasons = seasons or seasons_through_current()
    total = 0
    with db.JobRun("ingest_weekly_stats") as run:
        for s in seasons:
            try:
                w = nflverse.load("weekly_stats", s, columns=WS_COLS)
            except nflverse.NotAvailable as e:
                print(f"[weekly] {e}")
                continue
            w = w.rename(columns={"player_display_name": "player_name"})
            w = w[w.player_id.notna()]
            for c in ("team", "opponent_team"):
                w[c] = w[c].map(lambda v: norm(v) if isinstance(v, str) else v)
            w = w.drop_duplicates(["player_id", "season", "week", "season_type"])
            n = db.upsert(w, "raw_weekly_stats", ["player_id", "season", "week", "season_type"])
            print(f"[weekly] {s}: {n} rows")
            total += n
        run.rows = total
    return total


# ---------------------------------------------------------------- injuries (append-only history)
def ingest_injuries(seasons: list[int] | None = None) -> int:
    seasons = seasons or [current_season() - 1, current_season()]
    total = 0
    with db.JobRun("ingest_injuries") as run:
        for s in seasons:
            try:
                i = nflverse.load("injuries", s)
            except nflverse.NotAvailable as e:
                print(f"[injuries] {e}")
                continue
            i = i[["season", "week", "season_type", "team", "gsis_id", "full_name", "position",
                   "report_primary_injury", "report_status", "practice_primary_injury", "practice_status"]].copy()
            i["team"] = i["team"].map(norm)
            i = i.drop_duplicates(["season", "week", "season_type", "team", "gsis_id", "report_status", "practice_status"])
            i["source"] = "nflverse"
            # UNIQUE constraint makes re-runs no-ops; new statuses become new rows (history preserved)
            n = db.upsert(i, "raw_injuries",
                          ["season", "week", "season_type", "team", "gsis_id", "report_status", "practice_status", "source"],
                          update=False)
            total += n
        run.rows = total
    return total


# ---------------------------------------------------------------- depth charts / rosters / snaps
def ingest_depth_charts(seasons: list[int] | None = None) -> int:
    seasons = seasons or [current_season()]
    total = 0
    with db.JobRun("ingest_depth_charts") as run:
        for s in seasons:
            try:
                d = nflverse.load("depth_charts", s)
            except nflverse.NotAvailable as e:
                print(f"[depth] {e}")
                continue
            d = d[["dt", "team", "player_name", "gsis_id", "pos_grp", "pos_abb", "pos_slot", "pos_rank"]].copy()
            d["season"] = s
            d["dt"] = pd.to_datetime(d["dt"], utc=True)
            d["team"] = d["team"].map(norm)
            d = d[d.gsis_id.notna()].drop_duplicates(["dt", "team", "gsis_id", "pos_abb", "pos_slot"])
            total += db.upsert(d, "raw_depth_charts", ["dt", "team", "gsis_id", "pos_abb", "pos_slot"], update=False)
        run.rows = total
    return total


def ingest_rosters(seasons: list[int] | None = None) -> int:
    seasons = seasons or [current_season() - 1, current_season()]
    total = 0
    with db.JobRun("ingest_rosters") as run:
        for s in seasons:
            try:
                r = nflverse.load("rosters", s)
            except nflverse.NotAvailable as e:
                print(f"[rosters] {e}")
                continue
            r = r[["season", "team", "gsis_id", "full_name", "position", "depth_chart_position", "status",
                   "years_exp", "headshot_url"]].copy()
            r = r[r.gsis_id.notna()].drop_duplicates(["season", "gsis_id"])
            r["team"] = r["team"].map(norm)
            total += db.upsert(r, "raw_rosters", ["season", "gsis_id"])
        run.rows = total
    return total


def ingest_snaps(seasons: list[int] | None = None) -> int:
    seasons = seasons or [current_season() - 1, current_season()]
    total = 0
    with db.JobRun("ingest_snaps") as run:
        for s in seasons:
            try:
                sc = nflverse.load("snap_counts", s)
            except nflverse.NotAvailable as e:
                print(f"[snaps] {e}")
                continue
            sc = sc[["game_id", "season", "week", "pfr_player_id", "player", "position", "team", "opponent",
                     "offense_snaps", "offense_pct", "defense_snaps", "defense_pct"]].copy()
            sc = sc[sc.pfr_player_id.notna()].drop_duplicates(["game_id", "pfr_player_id"])
            for c in ("team", "opponent"):
                sc[c] = sc[c].map(norm)
            total += db.upsert(sc, "raw_snap_counts", ["game_id", "pfr_player_id"])
        run.rows = total
    return total
