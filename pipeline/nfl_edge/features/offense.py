"""Team offense features, point-in-time (same blending scheme as defense.py)."""
from __future__ import annotations
import numpy as np
import pandas as pd
from .. import db
from .defense import PRIOR_K, PRIOR_SHRINK

METRICS = ["plays_pg", "pass_rate", "proe", "sec_per_play", "epa_per_play", "pass_epa_per_db", "pass_yds_pg"]


def offense_game_table(seasons: list[int]) -> pd.DataFrame:
    pbp = db.read_sql("""
        SELECT season, week, game_id, posteam, play_type, qb_dropback, epa, passing_yards, pass_oe,
               game_seconds_remaining
        FROM raw_pbp WHERE season = ANY(:s) AND season_type='REG' AND play_type IN ('pass','run')
    """, {"s": seasons})
    pbp["is_pass"] = (pbp.play_type == "pass").astype(int)
    pbp["pyds"] = pbp.passing_yards.fillna(0)
    pbp["pass_epa"] = np.where(pbp.qb_dropback == 1, pbp.epa, np.nan)
    g = pbp.groupby(["season", "week", "game_id", "posteam"]).agg(
        plays=("play_type", "size"), passes=("is_pass", "sum"), dropbacks=("qb_dropback", "sum"),
        epa_sum=("epa", "sum"), pass_epa_sum=("pass_epa", "sum"), pass_yds=("pyds", "sum"),
        proe_sum=("pass_oe", "sum"), proe_n=("pass_oe", "count"),
    ).reset_index()
    return g


def _aggregate(g: pd.DataFrame) -> pd.DataFrame:
    a = g.groupby("posteam").agg(games=("game_id", "nunique"), plays=("plays", "sum"), passes=("passes", "sum"),
                                 dropbacks=("dropbacks", "sum"), epa_sum=("epa_sum", "sum"),
                                 pass_epa_sum=("pass_epa_sum", "sum"), pass_yds=("pass_yds", "sum"),
                                 proe_sum=("proe_sum", "sum"), proe_n=("proe_n", "sum"))
    out = pd.DataFrame(index=a.index)
    out["games"] = a.games
    out["plays_pg"] = a.plays / a.games
    out["pass_rate"] = a.passes / a.plays
    out["proe"] = a.proe_sum / a.proe_n.replace(0, np.nan) / 100.0  # nflverse pass_oe is in percent
    out["sec_per_play"] = 3600.0 / (a.plays / a.games) / 2  # rough: each team has ~half the clock
    out["epa_per_play"] = a.epa_sum / a.plays
    out["pass_epa_per_db"] = a.pass_epa_sum / a.dropbacks.replace(0, np.nan)
    out["pass_yds_pg"] = a.pass_yds / a.games
    return out


def build_offense_features(seasons: list[int], target_weeks: pd.DataFrame | None = None) -> pd.DataFrame:
    all_seasons = sorted(set(seasons) | {min(seasons) - 1})
    g = offense_game_table(all_seasons)
    if target_weeks is None:
        target_weeks = db.read_sql("""SELECT season, week, min(kickoff_utc) - interval '6 hours' AS as_of
                                      FROM raw_games WHERE season = ANY(:s) AND game_type='REG'
                                      GROUP BY 1,2 ORDER BY 1,2""", {"s": seasons})
    prior_cache = {}

    def prior(season):
        if season not in prior_cache:
            gs = g[g.season == season]
            prior_cache[season] = _aggregate(gs) if len(gs) else pd.DataFrame()
        return prior_cache[season]

    rows = []
    for _, t in target_weeks.iterrows():
        s, w = int(t.season), int(t.week)
        cur = g[(g.season == s) & (g.week < w)]
        cur_agg = _aggregate(cur) if len(cur) else pd.DataFrame(columns=["games"] + METRICS)
        pr = prior(s - 1)
        teams = sorted(set(cur_agg.index) | set(pr.index))
        out = pd.DataFrame(index=teams)
        out["games"] = cur_agg.games.reindex(teams).fillna(0).astype(int)
        for m in METRICS:
            c = cur_agg[m].reindex(teams) if m in cur_agg else pd.Series(np.nan, index=teams)
            n = out.games.astype(float)
            if len(pr) and m in pr:
                p = pr[m].reindex(teams)
                p = PRIOR_SHRINK * p + (1 - PRIOR_SHRINK) * p.mean()
            else:
                p = pd.Series(c.mean() if c.notna().any() else np.nan, index=teams)
            blended = (n * c.fillna(0) + PRIOR_K * p) / (n + PRIOR_K)
            out[m] = blended.where(p.notna(), c)
        out["season"], out["week"], out["as_of"], out["team"] = s, w, t.as_of, out.index
        rows.append(out.reset_index(drop=True))
    return pd.concat(rows, ignore_index=True)


def write_offense_features(seasons: list[int]) -> int:
    return db.upsert(build_offense_features(seasons), "feat_team_offense", ["season", "week", "team"])
