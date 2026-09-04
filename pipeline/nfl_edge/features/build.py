"""Assemble feat_player_game rows (passing-yards market) for training seasons and the target week.

Point-in-time guarantee: every row's as_of = (earliest kickoff of that season-week) − 6h, and all
inputs are restricted to games with week < row.week (same season) or earlier seasons. A test in
tests/test_leakage.py asserts as_of < kickoff_utc for every stored row.
"""
from __future__ import annotations
import datetime as dt
import json
import numpy as np
import pandas as pd
from .. import db
from ..config import FIRST_TRAIN_SEASON
from ..ingest.nflverse_jobs import current_season
from ..ingest.odds_jobs import target_week
from .defense import build_defense_features
from .offense import build_offense_features
from .players import qb_game_log, qb_features, current_qb1, MIN_ATTEMPTS
from .skill import skill_game_log, skill_features, current_skill_players
from .context import coach_regime, injury_context

DEF_COLS = ["pass_yds_allowed_pg", "pass_yds_allowed_rank", "pass_epa_allowed", "pass_epa_allowed_rank",
            "yds_per_dropback_allowed", "yds_per_dropback_rank", "sack_rate", "explosive_pass_rate_allowed",
            "yac_per_comp_allowed", "wr_yds_allowed_pg", "te_yds_allowed_pg", "sos_adj_pass_yds_allowed",
            "sos_adj_pass_rank", "dropbacks_faced_pg", "rush_yds_allowed_pg", "rush_epa_allowed", "games"]
OFF_COLS = ["plays_pg", "pass_rate", "proe", "epa_per_play", "pass_epa_per_db", "pass_yds_pg", "games",
            "neutral_pass_rate", "neutral_plays_pg", "shotgun_rate", "no_huddle_rate"]
INJ_COLS = ["skill_out", "ol_out", "target_share_out", "wr1_out"]
OPP_INJ_COLS = ["db_out", "front_out"]


def game_context(seasons: list[int]) -> pd.DataFrame:
    """One row per (game, team) with market/context features from raw_games (+ latest weather)."""
    g = db.read_sql("""SELECT game_id, season, week, kickoff_utc, home_team, away_team, spread_line, total_line,
                              div_game, roof, home_rest, away_rest, temp, wind, gametime, weekday
                       FROM raw_games WHERE season = ANY(:s) AND game_type='REG'""", {"s": seasons})
    w = db.read_sql("""SELECT DISTINCT ON (game_id) game_id, temp_f, wind_mph, precip_prob, is_dome
                       FROM raw_weather ORDER BY game_id, fetched_at DESC""")
    g = g.merge(w, on="game_id", how="left")
    rows = []
    for _, r in g.iterrows():
        dome = 1 if str(r.roof) in ("dome", "closed") else 0
        hour = int(str(r.gametime)[:2]) if isinstance(r.gametime, str) and r.gametime[:2].isdigit() else 13
        primetime = 1 if hour >= 19 else 0
        temp = r.temp_f if pd.notna(r.temp_f) else r.temp
        wind = r.wind_mph if pd.notna(r.wind_mph) else r.wind
        for team, opp, home in ((r.home_team, r.away_team, 1), (r.away_team, r.home_team, 0)):
            # nflverse spread_line is home-team-relative and POSITIVE when home is favored
            spread_team = -r.spread_line if home else r.spread_line  # negative = this team favored
            rows.append({
                "game_id": r.game_id, "season": r.season, "week": r.week, "kickoff_utc": r.kickoff_utc,
                "team": team, "opponent": opp, "is_home": home,
                "spread_team": spread_team, "total_line": r.total_line,
                "implied_total": (r.total_line - spread_team) / 2 if pd.notna(r.total_line) and pd.notna(spread_team) else np.nan,
                "div_game": r.div_game, "dome": dome, "primetime": primetime,
                "rest_days": r.home_rest if home else r.away_rest,
                "temp": (temp if not dome else 70), "wind": (wind if not dome else 0),
            })
    return pd.DataFrame(rows)


def build_features(seasons: list[int] | None = None, week: int | None = None) -> int:
    """Build + upsert feat_team_defense, feat_team_offense, feat_player_game.

    seasons: training seasons to (re)build (default FIRST_TRAIN_SEASON..current). The target
    week of the current season is always built too.
    """
    cur_season, cur_week = target_week()
    if week:
        cur_week = week
    seasons = seasons or list(range(FIRST_TRAIN_SEASON, cur_season + 1))
    with db.JobRun("build_features") as run:
        # --- team features for every REG week + the target week
        tw = db.read_sql("""SELECT season, week, min(kickoff_utc) - interval '6 hours' AS as_of
                            FROM raw_games WHERE season = ANY(:s) AND game_type='REG' GROUP BY 1,2 ORDER BY 1,2""",
                         {"s": seasons})
        tw["as_of"] = pd.to_datetime(tw.as_of, utc=True)
        regime = coach_regime(seasons)
        dfe = build_defense_features(seasons, tw)
        off = build_offense_features(seasons, tw, regime)
        db.upsert(dfe, "feat_team_defense", ["season", "week", "team"])
        db.upsert(off, "feat_team_offense", ["season", "week", "team"])

        # --- player rows: history + pseudo-rows for the target week
        log = qb_game_log(seasons)
        ctx = game_context(seasons)
        now = dt.datetime.now(dt.timezone.utc)
        target_games = ctx[(ctx.season == cur_season) & (ctx.week == cur_week)]
        played = set(log[(log.season == cur_season) & (log.week == cur_week)].game_id)
        as_of_target = tw[(tw.season == cur_season) & (tw.week == cur_week)].as_of.iloc[0]
        qb1 = current_qb1(cur_season, min(as_of_target, pd.Timestamp(now)))
        pseudo = target_games[~target_games.game_id.isin(played)].merge(qb1, on="team", how="left")
        pseudo = pseudo[pseudo.player_id.notna()]
        pseudo_rows = pd.DataFrame({
            "player_id": pseudo.player_id, "player_name": pseudo.player_name, "position": "QB",
            "season": pseudo.season, "week": pseudo.week, "team": pseudo.team, "opponent": pseudo.opponent,
            "game_id": pseudo.game_id, "kickoff_utc": pseudo.kickoff_utc,
        })
        full = pd.concat([log, pseudo_rows], ignore_index=True)
        feats = qb_features(full)
        # league passing environment: mean starter passing yards over the previous 8 league-weeks
        # (spans seasons; tracks era drift such as the 2023-25 league-wide passing decline)
        env = feats[feats.attempts >= MIN_ATTEMPTS].groupby(["season", "week"]).agg(
            league_py=("passing_yards", "mean"), league_att=("attempts", "mean")).sort_index().reset_index()
        env["league_py_l8"] = env.league_py.shift(1).rolling(8, min_periods=3).mean()
        env["league_att_l8"] = env.league_att.shift(1).rolling(8, min_periods=3).mean()
        env["league_py_prev_season"] = env.season.map(env.groupby("season").league_py.mean().shift(1))
        feats = feats.merge(env[["season", "week", "league_py_l8", "league_att_l8", "league_py_prev_season"]],
                            on=["season", "week"], how="left")
        # target week has no rows in env: forward-fill from the latest completed week
        for c in ("league_py_l8", "league_att_l8", "league_py_prev_season"):
            feats[c] = feats[c].fillna(env[c].dropna().iloc[-1] if env[c].notna().any() else np.nan)

        # join team features + context
        feats = feats.merge(ctx.drop(columns=["kickoff_utc"]), on=["game_id", "season", "week", "team", "opponent"], how="left")
        d = dfe[["season", "week", "team"] + DEF_COLS].rename(columns={c: f"opp_{c}" for c in DEF_COLS})
        feats = feats.merge(d, left_on=["season", "week", "opponent"], right_on=["season", "week", "team"],
                            how="left", suffixes=("", "_d")).drop(columns=["team_d"])
        o = off[["season", "week", "team"] + OFF_COLS].rename(columns={c: f"team_{c}" for c in OFF_COLS})
        feats = feats.merge(o, on=["season", "week", "team"], how="left")
        feats = feats.merge(tw, on=["season", "week"], how="left")
        # v2 context: coaching regime + injuries (own skill/OL outs, opponent secondary/front outs)
        feats = feats.merge(regime, on=["season", "team"], how="left")
        feats[["new_hc", "coach_tenure"]] = feats[["new_hc", "coach_tenure"]].fillna({"new_hc": 0, "coach_tenure": 2})
        inj = injury_context(seasons)
        own = inj[["season", "week", "team"] + INJ_COLS]
        feats = feats.merge(own, on=["season", "week", "team"], how="left")
        opp = inj[["season", "week", "team"] + OPP_INJ_COLS].rename(columns={"team": "opponent", **{c: f"opp_{c}" for c in OPP_INJ_COLS}})
        feats = feats.merge(opp, on=["season", "week", "opponent"], how="left")
        for c in INJ_COLS + [f"opp_{c}" for c in OPP_INJ_COLS]:
            feats[c] = feats[c].fillna(0)
        seen = set(zip(inj.season, inj.week))
        feats["injury_report_seen"] = [int((s_, w_) in seen) for s_, w_ in zip(feats.season, feats.week)]

        feature_cols = [c for c in feats.columns if c not in {
            "player_id", "player_name", "position", "season", "week", "team", "opponent", "game_id", "kickoff_utc",
            "as_of", "completions", "attempts", "passing_yards", "passing_tds", "passing_interceptions",
            "sacks_suffered", "passing_air_yards", "passing_epa", "passing_cpoe", "carries", "rushing_yards",
            "starter", "ypa", "epa_per_att", "sack_rate"}]
        feats["week_num"] = feats.week
        feature_cols.append("week_num")

        keep = feats[(feats.starter == 1) | feats.attempts.isna()]  # training starters + target pseudo-rows
        out = pd.DataFrame({
            "season": keep.season, "week": keep.week, "game_id": keep.game_id, "player_id": keep.player_id,
            "player_name": keep.player_name, "position": "QB", "team": keep.team, "opponent": keep.opponent,
            "is_home": keep.is_home.astype(bool), "kickoff_utc": pd.to_datetime(keep.kickoff_utc, utc=True),
            "as_of": pd.to_datetime(keep.as_of, utc=True),
            "features": [json.dumps({k: (None if pd.isna(v) else float(v)) for k, v in row.items()})
                         for row in keep[feature_cols].to_dict("records")],
            "target_passing_yards": keep.passing_yards, "target_attempts": keep.attempts,
        })
        assert (out.as_of < out.kickoff_utc).all(), "point-in-time violation"
        n_qb = db.upsert(out, "feat_player_game", ["season", "week", "player_id", "game_id"])
        print(f"[features] {n_qb} QB-game rows, {int(out.target_attempts.isna().sum())} for {cur_season} wk{cur_week}, {len(feature_cols)} features")

        # ---------------- skill positions (WR/TE/RB): receiving yards, receptions, rushing yards
        skill_out = _skill_rows(seasons, ctx, dfe, off, tw, regime, inj, cur_season, cur_week, as_of_target, now)
        n_sk = db.upsert(skill_out, "feat_player_game", ["season", "week", "player_id", "game_id"]) if len(skill_out) else 0
        print(f"[features] {n_sk} skill-game rows, {int(skill_out.target_targets.isna().sum()) if len(skill_out) else 0} for {cur_season} wk{cur_week}")
        run.rows = n_qb + n_sk
        run.detail = {"seasons": seasons, "target": [cur_season, cur_week], "qb_rows": n_qb, "skill_rows": n_sk,
                      "n_features": len(feature_cols)}
        return run.rows


SKILL_ID_COLS = {"player_id", "player_name", "position", "season", "week", "team", "opponent", "game_id", "kickoff_utc", "as_of",
                 "active", "touches", "team_targets", "team_carries", "tgt_share", "carry_share", "ypt", "catch_rate", "adot", "ypc"}
SKILL_STAT_COLS = {"targets", "receptions", "receiving_yards", "receiving_air_yards", "receiving_yards_after_catch", "target_share",
                   "air_yards_share", "wopr", "carries", "rushing_yards", "receiving_tds", "rushing_tds"}


def _skill_rows(seasons, ctx, dfe, off, tw, regime, inj, cur_season, cur_week, as_of_target, now) -> pd.DataFrame:
    log = skill_game_log(seasons)
    target_games = ctx[(ctx.season == cur_season) & (ctx.week == cur_week)]
    played = set(log[(log.season == cur_season) & (log.week == cur_week)].game_id)
    tg = target_games[~target_games.game_id.isin(played)]
    ros = current_skill_players(cur_season, tg.team.tolist())
    # only players with at least one prior active game (rookies with no history get no projection yet)
    seen = set(log[log.targets.fillna(0) + log.carries.fillna(0) >= 1].player_id)
    ros = ros[ros.player_id.isin(seen)]
    pseudo = tg.merge(ros, on="team", how="inner")
    pseudo_rows = pd.DataFrame({
        "player_id": pseudo.player_id, "player_name": pseudo.player_name, "position": pseudo.position,
        "season": pseudo.season, "week": pseudo.week, "team": pseudo.team, "opponent": pseudo.opponent,
        "game_id": pseudo.game_id, "kickoff_utc": pseudo.kickoff_utc,
    })
    full = pd.concat([log, pseudo_rows], ignore_index=True)
    feats = skill_features(full)
    # league environment per market (previous-season means over active games; forward-filled for the target week)
    act = feats[feats.active == 1]
    env = act.groupby("season").agg(league_recy=("receiving_yards", "mean"), league_rec=("receptions", "mean")).reset_index()
    env_rb = act[act.position.isin(["RB", "FB"]) & (act.carries >= 5)].groupby("season").rushing_yards.mean().rename("league_ruy").reset_index()
    env = env.merge(env_rb, on="season", how="left").sort_values("season")
    for c in ("league_recy", "league_rec", "league_ruy"):
        env[f"{c}_prev_season"] = env[c].shift(1)
    feats = feats.merge(env[["season", "league_recy_prev_season", "league_rec_prev_season", "league_ruy_prev_season"]], on="season", how="left")
    for c in ("league_recy_prev_season", "league_rec_prev_season", "league_ruy_prev_season"):
        feats[c] = feats[c].fillna(env[c].dropna().iloc[-1] if env[c].notna().any() else np.nan)

    feats = feats.merge(ctx.drop(columns=["kickoff_utc"]), on=["game_id", "season", "week", "team", "opponent"], how="left")
    d = dfe[["season", "week", "team"] + DEF_COLS + ["wr_yds_allowed_rank", "te_yds_allowed_rank", "rb_rec_yds_allowed_pg",
                                                     "rb_rec_yds_allowed_rank", "rush_yds_allowed_rank", "rush_epa_allowed_rank"]]
    d = d.rename(columns={c: f"opp_{c}" for c in d.columns if c not in ("season", "week", "team")})
    feats = feats.merge(d, left_on=["season", "week", "opponent"], right_on=["season", "week", "team"], how="left", suffixes=("", "_d")).drop(columns=["team_d"])
    o = off[["season", "week", "team"] + OFF_COLS].rename(columns={c: f"team_{c}" for c in OFF_COLS})
    feats = feats.merge(o, on=["season", "week", "team"], how="left")
    feats = feats.merge(tw, on=["season", "week"], how="left")
    feats = feats.merge(regime, on=["season", "team"], how="left")
    feats[["new_hc", "coach_tenure"]] = feats[["new_hc", "coach_tenure"]].fillna({"new_hc": 0, "coach_tenure": 2})
    own = inj[["season", "week", "team"] + INJ_COLS]
    feats = feats.merge(own, on=["season", "week", "team"], how="left")
    opp = inj[["season", "week", "team"] + OPP_INJ_COLS].rename(columns={"team": "opponent", **{c: f"opp_{c}" for c in OPP_INJ_COLS}})
    feats = feats.merge(opp, on=["season", "week", "opponent"], how="left")
    for c in INJ_COLS + [f"opp_{c}" for c in OPP_INJ_COLS]:
        feats[c] = feats[c].fillna(0)
    seen_wk = set(zip(inj.season, inj.week))
    feats["injury_report_seen"] = [int((s_, w_) in seen_wk) for s_, w_ in zip(feats.season, feats.week)]
    feats["week_num"] = feats.week

    feature_cols = [c for c in feats.columns if c not in SKILL_ID_COLS | SKILL_STAT_COLS]
    # training rows: active games with a real role (≥2 touches EWM) — plus every target-week pseudo-row
    is_target = feats.targets.isna() & feats.carries.isna()
    keep = feats[((feats.active == 1) & (feats.touches_ewm.fillna(0) >= 2)) | is_target]
    out = pd.DataFrame({
        "season": keep.season, "week": keep.week, "game_id": keep.game_id, "player_id": keep.player_id,
        "player_name": keep.player_name, "position": keep.position, "team": keep.team, "opponent": keep.opponent,
        "is_home": keep.is_home.astype(bool), "kickoff_utc": pd.to_datetime(keep.kickoff_utc, utc=True),
        "as_of": pd.to_datetime(keep.as_of, utc=True),
        "features": [json.dumps({k: (None if pd.isna(v) else float(v)) for k, v in row.items()})
                     for row in keep[feature_cols].to_dict("records")],
        "target_receiving_yards": keep.receiving_yards, "target_receptions": keep.receptions,
        "target_rushing_yards": keep.rushing_yards, "target_targets": keep.targets, "target_carries": keep.carries,
    })
    assert (out.as_of < out.kickoff_utc).all(), "point-in-time violation (skill)"
    return out


def feature_names() -> list[str]:
    r = db.read_sql("SELECT features FROM feat_player_game LIMIT 1")
    return list(json.loads(r.features.iloc[0]).keys()) if len(r) else []
