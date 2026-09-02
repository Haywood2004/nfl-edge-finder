"""Per-QB point-in-time features from raw_weekly_stats.

Every row (player, season, week) uses ONLY that player's games strictly before (season, week).
Rolling windows are computed on the chronologically sorted game log, shifted by one.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from .. import db

MIN_ATTEMPTS = 10   # a "QB game" for training purposes


def qb_game_log(seasons: list[int]) -> pd.DataFrame:
    return db.read_sql("""
        SELECT w.player_id, w.player_name, w.position, w.season, w.week, w.team, w.opponent_team AS opponent,
               w.completions, w.attempts, w.passing_yards, w.passing_tds, w.passing_interceptions,
               w.sacks_suffered, w.passing_air_yards, w.passing_epa, w.passing_cpoe, w.carries, w.rushing_yards,
               g.game_id, g.kickoff_utc
        FROM raw_weekly_stats w
        JOIN raw_games g ON g.season=w.season AND g.week=w.week AND g.game_type='REG'
             AND (g.home_team=w.team OR g.away_team=w.team)
        WHERE w.season = ANY(:s) AND w.season_type='REG' AND w.position='QB'
        ORDER BY w.player_id, w.season, w.week
    """, {"s": seasons})


def qb_features(log: pd.DataFrame) -> pd.DataFrame:
    """Add point-in-time feature columns to a QB game log (one row per QB game).

    Rows with attempts < MIN_ATTEMPTS still get features (they are used as history) but the
    caller filters them out of the training target.
    """
    log = log.sort_values(["player_id", "season", "week"]).copy()
    log["starter"] = (log.attempts >= MIN_ATTEMPTS).astype(int)
    log["ypa"] = log.passing_yards / log.attempts.replace(0, np.nan)
    log["epa_per_att"] = log.passing_epa / log.attempts.replace(0, np.nan)
    log["sack_rate"] = log.sacks_suffered / (log.attempts + log.sacks_suffered).replace(0, np.nan)
    grp = log.groupby("player_id", group_keys=False)

    def roll(col, n, fn="mean"):
        return grp[col].transform(lambda s: getattr(s.shift(1).rolling(n, min_periods=1), fn)())

    # history restricted to starter games where it matters (yards in mop-up duty are not signal)
    for col in ("passing_yards", "attempts", "ypa", "epa_per_att", "passing_cpoe", "passing_air_yards", "rushing_yards", "sack_rate"):
        log[f"_{col}_s"] = log[col].where(log.starter == 1)
    sgrp = log.groupby("player_id", group_keys=False)

    def sroll(col, n, fn="mean"):
        return sgrp[f"_{col}_s"].transform(lambda s: getattr(s.shift(1).rolling(n, min_periods=1), fn)())

    f = pd.DataFrame(index=log.index)
    f["py_l3"] = sroll("passing_yards", 3)
    f["py_l5"] = sroll("passing_yards", 5)
    f["py_l10"] = sroll("passing_yards", 10)
    f["py_sd_l10"] = sroll("passing_yards", 10, "std")
    f["py_ewm"] = sgrp["_passing_yards_s"].transform(lambda s: s.shift(1).ewm(halflife=6, ignore_na=True).mean())
    f["att_l3"] = sroll("attempts", 3)
    f["att_l5"] = sroll("attempts", 5)
    f["att_ewm"] = sgrp["_attempts_s"].transform(lambda s: s.shift(1).ewm(halflife=6, ignore_na=True).mean())
    f["ypa_l10"] = sroll("ypa", 10)
    f["ypa_ewm"] = sgrp["_ypa_s"].transform(lambda s: s.shift(1).ewm(halflife=8, ignore_na=True).mean())
    f["epa_att_ewm"] = sgrp["_epa_per_att_s"].transform(lambda s: s.shift(1).ewm(halflife=8, ignore_na=True).mean())
    f["cpoe_ewm"] = sgrp["_passing_cpoe_s"].transform(lambda s: s.shift(1).ewm(halflife=8, ignore_na=True).mean())
    f["air_yds_ewm"] = sgrp["_passing_air_yards_s"].transform(lambda s: s.shift(1).ewm(halflife=8, ignore_na=True).mean())
    f["rush_yds_ewm"] = sgrp["_rushing_yards_s"].transform(lambda s: s.shift(1).ewm(halflife=8, ignore_na=True).mean())
    f["sack_rate_ewm"] = sgrp["_sack_rate_s"].transform(lambda s: s.shift(1).ewm(halflife=8, ignore_na=True).mean())

    # season-to-date and prior-season means (starter games)
    st = log.groupby(["player_id", "season"], group_keys=False)
    f["py_std_avg"] = st["_passing_yards_s"].transform(lambda s: s.shift(1).expanding().mean())
    f["games_std"] = st["starter"].transform(lambda s: s.shift(1).fillna(0).cumsum())
    season_avg = log[log.starter == 1].groupby(["player_id", "season"]).passing_yards.agg(["mean", "count"])
    prev = season_avg.reset_index()
    prev["season"] = prev.season + 1
    prev = prev.rename(columns={"mean": "py_prev_season", "count": "games_prev_season"})
    log2 = log[["player_id", "season"]].merge(prev, on=["player_id", "season"], how="left")
    f["py_prev_season"] = log2.py_prev_season.values
    f["games_prev_season"] = log2.games_prev_season.fillna(0).values
    f["games_career"] = sgrp["starter"].transform(lambda s: s.shift(1).fillna(0).cumsum())
    f["usage_trend"] = f.py_l3 - f.py_l10
    # team change vs previous game
    f["new_team"] = (grp["team"].shift(1) != log.team).astype(int).where(grp["team"].shift(1).notna(), 0)
    f["weeks_since_last"] = 0
    prev_kick = grp["kickoff_utc"].shift(1)
    f["days_since_last"] = ((pd.to_datetime(log.kickoff_utc, utc=True) - pd.to_datetime(prev_kick, utc=True))
                            .dt.total_seconds() / 86400)
    f = f.drop(columns=["weeks_since_last"])
    return pd.concat([log.drop(columns=[c for c in log.columns if c.startswith("_")]), f], axis=1)


def current_qb1(season: int, as_of) -> pd.DataFrame:
    """Team → QB1 from the latest depth chart at or before as_of (falls back to roster)."""
    dc = db.read_sql("""
        WITH latest AS (SELECT team, max(dt) dt FROM raw_depth_charts WHERE season=:s AND dt<=:a GROUP BY team)
        SELECT d.team, d.gsis_id AS player_id, d.player_name, d.pos_rank
        FROM raw_depth_charts d JOIN latest l ON l.team=d.team AND l.dt=d.dt
        WHERE d.pos_abb='QB' AND d.pos_rank=1
    """, {"s": season, "a": as_of})
    return dc.drop_duplicates("team")
