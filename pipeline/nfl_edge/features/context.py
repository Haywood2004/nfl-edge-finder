"""Regime + injury context features (v2), point-in-time.

coach_regime : per (season, team) — is the head coach new this season (vs the team's Week-1 coach the
               season before), and how many seasons the current coach has been in place. A new staff
               makes last season's team tendencies (pass rate, pace) much less informative; the model
               sees the flag and can discount prior-season inputs on its own.
injury_context: per (season, week, team) counts of players ruled Out/Doubtful on the final report by
               position group, plus the share of the team's prior targets that belong to Out receivers
               ("target_share_out") and a flag for the top target being out ("wr1_out"). The opponent's
               secondary / pass-rush outs are attached with an opp_ prefix downstream.

Point-in-time: injury rows for (season, week) are the official reports published before that week's
games; features for week w use only reports for week w plus target history from weeks < w.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from .. import db

OUT = ("Out", "Doubtful")
GROUPS = {
    "skill": {"WR", "TE", "RB", "FB"},
    "ol": {"T", "G", "C", "OT", "OG", "OL"},
    "qb": {"QB"},
    "db": {"CB", "S", "DB", "FS", "SS"},
    "front": {"DE", "DT", "LB", "OLB", "ILB", "MLB", "DL", "EDGE", "NT"},
}


def coach_regime(seasons: list[int]) -> pd.DataFrame:
    g = db.read_sql("""SELECT season, week, home_team AS team, home_coach AS coach FROM raw_games
                       WHERE game_type='REG' AND home_coach IS NOT NULL
                       UNION ALL
                       SELECT season, week, away_team, away_coach FROM raw_games
                       WHERE game_type='REG' AND away_coach IS NOT NULL""")
    first = g.sort_values(["team", "season", "week"]).groupby(["team", "season"]).coach.first().reset_index()
    first = first.sort_values(["team", "season"])
    first["prev_coach"] = first.groupby("team").coach.shift(1)
    first["new_hc"] = ((first.coach != first.prev_coach) & first.prev_coach.notna()).astype(int)
    # tenure: consecutive seasons with the same week-1 coach
    tenure = []
    for team, grp in first.groupby("team"):
        t = 0
        for _, r in grp.iterrows():
            t = t + 1 if r.coach == r.prev_coach else 1
            tenure.append((team, r.season, t))
    ten = pd.DataFrame(tenure, columns=["team", "season", "coach_tenure"])
    out = first.merge(ten, on=["team", "season"])
    return out[out.season.isin(seasons)][["season", "team", "new_hc", "coach_tenure"]]


def _final_status(seasons: list[int]) -> pd.DataFrame:
    """Latest reported status per (season, week, team, player), any source."""
    i = db.read_sql("""SELECT DISTINCT ON (season, week, team, gsis_id) season, week, team, gsis_id, position,
                              report_status, practice_status
                       FROM raw_injuries WHERE season = ANY(:s) AND season_type='REG'
                       ORDER BY season, week, team, gsis_id, id DESC""", {"s": seasons})
    i["out"] = i.report_status.isin(OUT).astype(int)
    return i


def _prior_targets(seasons: list[int]) -> pd.DataFrame:
    """Per (season, week, team, player): targets accumulated in weeks < week this season, and prior-season targets."""
    w = db.read_sql("""SELECT season, week, team, player_id, position, targets FROM raw_weekly_stats
                       WHERE season = ANY(:s) AND season_type='REG' AND position IN ('WR','TE','RB','FB')
                       AND targets IS NOT NULL""", {"s": sorted(set(seasons) | {min(seasons) - 1})})
    w = w.sort_values(["season", "team", "player_id", "week"])
    w["cum_targets"] = w.groupby(["season", "team", "player_id"]).targets.cumsum() - w.targets
    prev = w.groupby(["season", "player_id"]).targets.sum().reset_index().rename(columns={"targets": "prev_targets"})
    prev["season"] = prev.season + 1
    return w, prev


def injury_context(seasons: list[int]) -> pd.DataFrame:
    inj = _final_status(seasons)
    if inj.empty:
        return pd.DataFrame(columns=["season", "week", "team"])
    outs = inj[inj.out == 1].copy()
    outs["grp"] = outs.position.map(lambda p: next((k for k, v in GROUPS.items() if p in v), "other"))
    cnt = outs.pivot_table(index=["season", "week", "team"], columns="grp", values="gsis_id", aggfunc="count", fill_value=0)
    cnt = cnt.reindex(columns=list(GROUPS), fill_value=0).add_suffix("_out").reset_index()

    # target share of Out receivers: season-to-date targets (weeks < w), blended with prior season early on
    w, prev = _prior_targets(seasons)
    weeks = inj[["season", "week", "team"]].drop_duplicates()
    rows = []
    prev_idx = prev.set_index(["season", "player_id"]).prev_targets
    w_by = {k: g for k, g in w.groupby(["season", "team"])}
    outs_by = {k: set(g.gsis_id) for k, g in outs.groupby(["season", "week", "team"])}
    for (s, team), wk_df in weeks.groupby(["season", "team"]):
        tw = w_by.get((s, team), w.iloc[0:0])
        for wk in wk_df.week.unique():
            hist = tw[tw.week < wk]
            std = hist.groupby("player_id").targets.sum() if len(hist) else pd.Series(dtype=float)
            games = hist.week.nunique() if len(hist) else 0
            out_ids = outs_by.get((s, wk, team), set())
            # prior-season targets for players currently on the team's report or in its target history
            team_players = set(std.index) | out_ids
            pr = pd.Series({p: float(prev_idx.get((s, p), 0.0)) for p in team_players}, dtype=float)
            if pr.empty:
                rows.append({"season": s, "week": wk, "team": team, "target_share_out": 0.0, "wr1_out": 0})
                continue
            # blend: weight season-to-date by games/(games+4), prior-season scaled to per-game
            wgt = games / (games + 4.0)
            std_pg = std / max(games, 1)
            pr_pg = pr / 17.0
            blended = wgt * std_pg.reindex(pr.index).fillna(0) + (1 - wgt) * pr_pg
            total = blended.sum()
            out_share = float(blended.reindex(list(out_ids)).fillna(0).sum() / total) if total > 0 else 0.0
            top = blended.idxmax() if total > 0 else None
            rows.append({"season": s, "week": wk, "team": team, "target_share_out": out_share,
                         "wr1_out": int(top in out_ids) if top else 0})
    share = pd.DataFrame(rows)
    return cnt.merge(share, on=["season", "week", "team"], how="outer").fillna(0)
