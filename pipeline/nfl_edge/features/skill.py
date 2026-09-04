"""Point-in-time features for skill positions (WR / TE / RB / FB) — receiving yards, receptions, rushing yards.

Same rules as players.py (QB): every row uses only that player's games strictly before (season, week);
rolling windows are computed on the chronologically sorted log, shifted by one. "Active" games (≥1 target
or carry) are the history that matters — a healthy scratch or a mop-up cameo is not signal.

Role features are relative to the team: target share, air-yards share, the player's rank among his team's
target earners (from prior-game EWMs, so it is point-in-time), and carry share. The injury-redistribution
inputs (teammates ruled out, share of prior targets they held) come from features/context.py.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from .. import db

POSITIONS = ("WR", "TE", "RB", "FB")
STATS = ["targets", "receptions", "receiving_yards", "receiving_air_yards", "receiving_yards_after_catch",
         "target_share", "air_yards_share", "wopr", "carries", "rushing_yards", "receiving_tds", "rushing_tds"]


def skill_game_log(seasons: list[int]) -> pd.DataFrame:
    return db.read_sql(f"""
        SELECT w.player_id, w.player_name, w.position, w.season, w.week, w.team, w.opponent_team AS opponent,
               {", ".join("w." + c for c in STATS)}, g.game_id, g.kickoff_utc
        FROM raw_weekly_stats w
        JOIN raw_games g ON g.season=w.season AND g.week=w.week AND g.game_type='REG'
             AND (g.home_team=w.team OR g.away_team=w.team)
        WHERE w.season = ANY(:s) AND w.season_type='REG' AND w.position IN ('WR','TE','RB','FB')
        ORDER BY w.player_id, w.season, w.week
    """, {"s": seasons})


def skill_features(log: pd.DataFrame) -> pd.DataFrame:
    log = log.sort_values(["player_id", "season", "week"]).copy()
    for c in STATS:
        log[c] = pd.to_numeric(log[c], errors="coerce")
    log["touches"] = log.targets.fillna(0) + log.carries.fillna(0)
    log["active"] = (log.touches >= 1).astype(int)
    log["ypt"] = log.receiving_yards / log.targets.replace(0, np.nan)
    log["catch_rate"] = log.receptions / log.targets.replace(0, np.nan)
    log["adot"] = log.receiving_air_yards / log.targets.replace(0, np.nan)
    log["ypc"] = log.rushing_yards / log.carries.replace(0, np.nan)
    # team totals per game (for shares) — from the same log, so point-in-time by construction
    tt = log.groupby(["season", "week", "team"]).agg(team_targets=("targets", "sum"), team_carries=("carries", "sum")).reset_index()
    log = log.merge(tt, on=["season", "week", "team"], how="left")
    log["carry_share"] = log.carries / log.team_carries.replace(0, np.nan)
    log["tgt_share"] = log.targets / log.team_targets.replace(0, np.nan)   # recomputed (nflverse target_share can be NaN)

    hist_cols = ["targets", "receptions", "receiving_yards", "receiving_air_yards", "tgt_share", "air_yards_share",
                 "wopr", "carries", "rushing_yards", "ypt", "catch_rate", "adot", "ypc", "carry_share", "touches"]
    for c in hist_cols:
        log[f"_{c}"] = log[c].where(log.active == 1)
    grp = log.groupby("player_id", group_keys=False)

    def roll(col, n, fn="mean"):
        return grp[f"_{col}"].transform(lambda s: getattr(s.shift(1).rolling(n, min_periods=1), fn)())

    def ewm(col, hl=5):
        return grp[f"_{col}"].transform(lambda s: s.shift(1).ewm(halflife=hl, ignore_na=True).mean())

    f = pd.DataFrame(index=log.index)
    for col, short in (("targets", "tgt"), ("receptions", "rec"), ("receiving_yards", "recy"), ("carries", "car"), ("rushing_yards", "ruy")):
        f[f"{short}_l3"] = roll(col, 3)
        f[f"{short}_l5"] = roll(col, 5)
        f[f"{short}_l10"] = roll(col, 10)
        f[f"{short}_ewm"] = ewm(col)
    f["recy_sd_l10"] = roll("receiving_yards", 10, "std")
    f["ruy_sd_l10"] = roll("rushing_yards", 10, "std")
    f["rec_sd_l10"] = roll("receptions", 10, "std")
    for col in ("tgt_share", "air_yards_share", "wopr", "ypt", "catch_rate", "adot", "ypc", "carry_share", "receiving_air_yards", "touches"):
        f[f"{col}_ewm"] = ewm(col)
    f["tgt_share_l3"] = roll("tgt_share", 3)
    f["carry_share_l3"] = roll("carry_share", 3)

    # season-to-date / previous season / career
    st = log.groupby(["player_id", "season"], group_keys=False)
    f["games_std"] = st["active"].transform(lambda s: s.shift(1).fillna(0).cumsum())
    f["recy_std_avg"] = st["_receiving_yards"].transform(lambda s: s.shift(1).expanding().mean())
    f["ruy_std_avg"] = st["_rushing_yards"].transform(lambda s: s.shift(1).expanding().mean())
    prev = (log[log.active == 1].groupby(["player_id", "season"])
            .agg(recy_prev_season=("receiving_yards", "mean"), rec_prev_season=("receptions", "mean"),
                 tgt_prev_season=("targets", "mean"), tgt_share_prev_season=("tgt_share", "mean"),
                 ruy_prev_season=("rushing_yards", "mean"), car_prev_season=("carries", "mean"),
                 games_prev_season=("active", "sum")).reset_index())
    prev["season"] = prev.season + 1
    m = log[["player_id", "season"]].merge(prev, on=["player_id", "season"], how="left")
    for c in ("recy_prev_season", "rec_prev_season", "tgt_prev_season", "tgt_share_prev_season", "ruy_prev_season", "car_prev_season"):
        f[c] = m[c].values
    f["games_prev_season"] = m.games_prev_season.fillna(0).values
    f["games_career"] = grp["active"].transform(lambda s: s.shift(1).fillna(0).cumsum())
    f["usage_trend"] = f.tgt_l3 - f.tgt_l10
    f["carry_trend"] = f.car_l3 - f.car_l10
    f["new_team"] = (grp["team"].shift(1) != log.team).astype(int).where(grp["team"].shift(1).notna(), 0)
    prev_kick = grp["kickoff_utc"].shift(1)
    f["days_since_last"] = ((pd.to_datetime(log.kickoff_utc, utc=True) - pd.to_datetime(prev_kick, utc=True)).dt.total_seconds() / 86400)
    f["pos_wr"] = (log.position == "WR").astype(int)
    f["pos_te"] = (log.position == "TE").astype(int)
    f["pos_rb"] = (log.position.isin(["RB", "FB"])).astype(int)

    out = pd.concat([log.drop(columns=[c for c in log.columns if c.startswith("_")]), f], axis=1)
    # team role rank: rank of tgt_ewm among the team's players that week (point-in-time: ewm uses prior games)
    out["tgt_rank_team"] = out.groupby(["season", "week", "team"]).tgt_ewm.rank(ascending=False, method="min")
    out["car_rank_team"] = out.groupby(["season", "week", "team"]).car_ewm.rank(ascending=False, method="min")
    return out


def current_skill_players(season: int, teams: list[str]) -> pd.DataFrame:
    """Rostered WR/TE/RB/FB for the target week (roster snapshot for the season)."""
    r = db.read_sql("""SELECT DISTINCT ON (gsis_id) gsis_id AS player_id, full_name AS player_name, position, team
                       FROM raw_rosters WHERE season=:s AND position IN ('WR','TE','RB','FB') AND team = ANY(:t)
                       ORDER BY gsis_id, (status='ACT') DESC""", {"s": season, "t": teams})
    return r
