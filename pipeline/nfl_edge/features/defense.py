"""Team defense features, point-in-time.

For a target (season, week) the features use only games from that season with week < target
week, blended with the prior season when the sample is small:

    value = (n_cur * cur + K * prior_shrunk) / (n_cur + K),   K = 6 games-equivalent
    prior_shrunk = 0.5 * prior_season_value + 0.5 * league_mean   (defense regresses hard YoY)

Week 1 therefore equals the shrunk prior season; by ~Week 8 the current season dominates.
Ranks are 1 = stingiest (fewest yards / lowest EPA allowed), 32 = most generous.

Position splits (WR/TE/RB receiving yards allowed) come from raw_weekly_stats (which carries
position and opponent); everything else from raw_pbp.

SOS adjustment: for each game, yards allowed minus what that offense averages against
everyone else that season (point-in-time approximation: that offense's season-to-date average
before the target week), plus league mean.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from .. import db

PRIOR_K = 6.0
PRIOR_SHRINK = 0.5
METRICS = {
    # name: (higher is worse for the defense?)  → rank ascending means rank 1 = best defense
    "pass_yds_allowed_pg": True, "pass_epa_allowed": True, "rush_yds_allowed_pg": True,
    "rush_epa_allowed": True, "yds_per_dropback_allowed": True, "wr_yds_allowed_pg": True,
    "te_yds_allowed_pg": True, "rb_rec_yds_allowed_pg": True, "sos_adj_pass_yds_allowed": True,
}
RANKED = {"pass_yds_allowed_pg": "pass_yds_allowed_rank", "pass_epa_allowed": "pass_epa_allowed_rank",
          "rush_yds_allowed_pg": "rush_yds_allowed_rank", "rush_epa_allowed": "rush_epa_allowed_rank",
          "yds_per_dropback_allowed": "yds_per_dropback_rank", "wr_yds_allowed_pg": "wr_yds_allowed_rank",
          "te_yds_allowed_pg": "te_yds_allowed_rank", "rb_rec_yds_allowed_pg": "rb_rec_yds_allowed_rank",
          "sos_adj_pass_yds_allowed": "sos_adj_pass_rank"}


def defense_game_table(seasons: list[int]) -> pd.DataFrame:
    """One row per (season, week, game_id, defteam) with raw per-game defensive totals."""
    pbp = db.read_sql("""
        SELECT season, week, game_id, defteam, posteam, pass, rush, qb_dropback, sack, complete_pass,
               passing_yards, rushing_yards, yards_after_catch, epa, yards_gained, play_type
        FROM raw_pbp WHERE season = ANY(:s) AND season_type='REG' AND play_type IN ('pass','run')
    """, {"s": seasons})
    pbp["is_pass"] = (pbp.play_type == "pass").astype(int)
    pbp["is_rush"] = (pbp.play_type == "run").astype(int)
    pbp["pyds"] = pbp.passing_yards.fillna(0)
    pbp["ryds"] = pbp.rushing_yards.fillna(0)
    pbp["pass_epa"] = np.where(pbp.qb_dropback == 1, pbp.epa, np.nan)
    pbp["rush_epa"] = np.where(pbp.is_rush == 1, pbp.epa, np.nan)
    pbp["explosive_pass"] = ((pbp.is_pass == 1) & (pbp.yards_gained >= 20)).astype(int)
    pbp["yac"] = np.where(pbp.complete_pass == 1, pbp.yards_after_catch.fillna(0), np.nan)
    g = pbp.groupby(["season", "week", "game_id", "defteam", "posteam"]).agg(
        dropbacks=("qb_dropback", "sum"), pass_plays=("is_pass", "sum"), rush_plays=("is_rush", "sum"),
        sacks=("sack", "sum"), completions=("complete_pass", "sum"),
        pass_yds=("pyds", "sum"), rush_yds=("ryds", "sum"),
        pass_epa_sum=("pass_epa", "sum"), rush_epa_sum=("rush_epa", "sum"),
        explosive_pass=("explosive_pass", "sum"), yac_sum=("yac", "sum"),
    ).reset_index()

    # receiving yards allowed by position (from weekly stats: opponent_team = the defense)
    ws = db.read_sql("""
        SELECT season, week, opponent_team AS defteam, position, receiving_yards
        FROM raw_weekly_stats WHERE season = ANY(:s) AND season_type='REG' AND position IN ('WR','TE','RB')
    """, {"s": seasons})
    pos = ws.pivot_table(index=["season", "week", "defteam"], columns="position", values="receiving_yards",
                         aggfunc="sum", fill_value=0).reset_index()
    pos = pos.rename(columns={"WR": "wr_yds", "TE": "te_yds", "RB": "rb_rec_yds"})
    g = g.merge(pos, on=["season", "week", "defteam"], how="left")
    for c in ("wr_yds", "te_yds", "rb_rec_yds"):
        if c not in g:
            g[c] = np.nan
    return g


def _aggregate(g: pd.DataFrame) -> pd.DataFrame:
    """Season-level per-team metrics from game rows."""
    a = g.groupby("defteam").agg(
        games=("game_id", "nunique"), dropbacks=("dropbacks", "sum"), pass_plays=("pass_plays", "sum"),
        rush_plays=("rush_plays", "sum"), sacks=("sacks", "sum"), completions=("completions", "sum"),
        pass_yds=("pass_yds", "sum"), rush_yds=("rush_yds", "sum"), pass_epa_sum=("pass_epa_sum", "sum"),
        rush_epa_sum=("rush_epa_sum", "sum"), explosive_pass=("explosive_pass", "sum"), yac_sum=("yac_sum", "sum"),
        wr_yds=("wr_yds", "sum"), te_yds=("te_yds", "sum"), rb_rec_yds=("rb_rec_yds", "sum"),
        sos_adj_sum=("sos_adj", "sum"),
    )
    out = pd.DataFrame(index=a.index)
    out["games"] = a.games
    out["pass_yds_allowed_pg"] = a.pass_yds / a.games
    out["pass_epa_allowed"] = a.pass_epa_sum / a.dropbacks.replace(0, np.nan)
    out["rush_yds_allowed_pg"] = a.rush_yds / a.games
    out["rush_epa_allowed"] = a.rush_epa_sum / a.rush_plays.replace(0, np.nan)
    out["dropbacks_faced_pg"] = a.dropbacks / a.games
    out["yds_per_dropback_allowed"] = a.pass_yds / a.dropbacks.replace(0, np.nan)
    out["sack_rate"] = a.sacks / a.dropbacks.replace(0, np.nan)
    out["explosive_pass_rate_allowed"] = a.explosive_pass / a.pass_plays.replace(0, np.nan)
    out["yac_per_comp_allowed"] = a.yac_sum / a.completions.replace(0, np.nan)
    out["wr_yds_allowed_pg"] = a.wr_yds / a.games
    out["te_yds_allowed_pg"] = a.te_yds / a.games
    out["rb_rec_yds_allowed_pg"] = a.rb_rec_yds / a.games
    out["sos_adj_pass_yds_allowed"] = a.sos_adj_sum / a.games
    return out


def _with_sos(g: pd.DataFrame) -> pd.DataFrame:
    """Add sos_adj = pass_yds − (that offense's avg pass yds in its OTHER games in this slice) + league mean."""
    g = g.copy()
    off = g.groupby(["season", "posteam"]).pass_yds.agg(["sum", "count"]).rename(columns={"sum": "o_sum", "count": "o_n"})
    g = g.merge(off, left_on=["season", "posteam"], right_index=True, how="left")
    league = g.pass_yds.mean()
    other_avg = (g.o_sum - g.pass_yds) / (g.o_n - 1).replace(0, np.nan)
    g["sos_adj"] = g.pass_yds - other_avg.fillna(league) + league
    return g.drop(columns=["o_sum", "o_n"])


def build_defense_features(seasons: list[int], target_weeks: pd.DataFrame | None = None) -> pd.DataFrame:
    """Return feat_team_defense rows for every (season, week) in `seasons` (weeks 1..max+1).

    target_weeks: optional DataFrame[season, week, as_of] — defaults to all REG weeks in raw_games.
    """
    all_seasons = sorted(set(seasons) | {min(seasons) - 1})
    g = defense_game_table(all_seasons)
    if target_weeks is None:
        target_weeks = db.read_sql("""SELECT season, week, min(kickoff_utc) - interval '6 hours' AS as_of
                                      FROM raw_games WHERE season = ANY(:s) AND game_type='REG'
                                      GROUP BY 1,2 ORDER BY 1,2""", {"s": seasons})
    metric_cols = list(METRICS) + ["dropbacks_faced_pg", "sack_rate", "explosive_pass_rate_allowed", "yac_per_comp_allowed"]
    # cache of full prior-season aggregates
    prior_cache: dict[int, pd.DataFrame] = {}

    def prior(season):
        if season not in prior_cache:
            gs = g[g.season == season]
            prior_cache[season] = _aggregate(_with_sos(gs)) if len(gs) else pd.DataFrame()
        return prior_cache[season]

    rows = []
    for _, t in target_weeks.iterrows():
        s, w = int(t.season), int(t.week)
        cur = g[(g.season == s) & (g.week < w)]
        cur_agg = _aggregate(_with_sos(cur)) if len(cur) else pd.DataFrame(columns=["games"] + metric_cols)
        pr = prior(s - 1)
        teams = sorted(set(cur_agg.index) | set(pr.index))
        out = pd.DataFrame(index=teams)
        out["games"] = cur_agg.games.reindex(teams).fillna(0).astype(int)
        for m in metric_cols:
            c = cur_agg[m].reindex(teams) if m in cur_agg else pd.Series(np.nan, index=teams)
            n = out.games.astype(float)
            if len(pr) and m in pr:
                p = pr[m].reindex(teams)
                p = PRIOR_SHRINK * p + (1 - PRIOR_SHRINK) * p.mean()
            else:
                p = pd.Series(c.mean() if c.notna().any() else np.nan, index=teams)
            blended = (n * c.fillna(0) + PRIOR_K * p) / (n + PRIOR_K)
            out[m] = blended.where(p.notna(), c)
        for m, r in RANKED.items():
            out[r] = out[m].rank(ascending=METRICS[m], method="min").astype("Int64")
        out["season"] = s
        out["week"] = w
        out["as_of"] = t.as_of
        out["team"] = out.index
        rows.append(out.reset_index(drop=True))
    return pd.concat(rows, ignore_index=True)


def write_defense_features(seasons: list[int]) -> int:
    df = build_defense_features(seasons)
    return db.upsert(df, "feat_team_defense", ["season", "week", "team"])
