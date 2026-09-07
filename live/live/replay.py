"""Validate the in-game model by replaying a season's play-by-play (raw_pbp, nflverse) at fixed checkpoints.

For every game and checkpoint (end of Q1, Q2, Q3, and 5:00 left in Q4) and every player with a pre-game projection,
compute the live projection from the state at that moment and compare with the actual final stat:
  live        y_t + mean_pre · usage_adj · remaining_share        (live/ingame.py)
  pregame     mean_pre                                            (baseline 1)
  naive_pace  y_t / f                                             (baseline 2)
  no_adj      y_t + mean_pre · (1 − f)                            (ablation: no usage/script adjustments)
Pre-game means come from the pipeline's models predicting on feat_player_game rows (2025 is a held-out test season
for every market), so the prior is exactly what the bot will have in production. Results → docs/MODEL.md ("Live").
"""
from __future__ import annotations
import datetime as dt
import json
import numpy as np
import pandas as pd
from nfl_edge import db
from nfl_edge.config import ROOT
from nfl_edge.models.passing_yards import load_latest as load_latest_py, MARKET as PASS_MARKET
from nfl_edge.models.player_props import load_latest as load_latest_prop, SPECS
from .ingame import project, naive_pace

CHECKPOINTS = [("end Q1", 2700), ("end Q2", 1800), ("end Q3", 900), ("Q4 5:00", 300)]
MARKET_COLS = {  # market → (stat column in pbp, player id column, opportunity id column, share feature)
    "player_pass_yds": ("passing_yards", "passer_player_id", "passer_player_id", None),
    "player_reception_yds": ("receiving_yards", "receiver_player_id", "receiver_player_id", "tgt_share_ewm"),
    "player_receptions": ("complete_pass", "receiver_player_id", "receiver_player_id", "tgt_share_ewm"),
    "player_rush_yds": ("rushing_yards", "rusher_player_id", "rusher_player_id", "carry_share_ewm"),
}


def _pregame_means(season: int, markets: list[str]) -> pd.DataFrame:
    """mean/sd per (game, player, market) from the pipeline models on that season's feature rows."""
    out = []
    feats = db.read_sql("""SELECT f.season, f.week, f.game_id, f.player_id, f.player_name, f.position, f.team, f.features
                           FROM feat_player_game f WHERE f.season=:s""", {"s": season})
    X_all = pd.DataFrame([json.loads(x) if isinstance(x, str) else x for x in feats.features]).astype(float)
    for m in markets:
        try:
            model, _ = load_latest_py() if m == PASS_MARKET else load_latest_prop(m)
        except RuntimeError as e:
            print(f"[replay] {m}: {e}"); continue
        if m == PASS_MARKET:
            mask = (feats.position == "QB").values
        else:
            spec = SPECS[m]
            mask = feats.position.isin(spec.positions).values & (X_all[spec.min_usage].fillna(0) >= spec.min_usage_val).values
        if not mask.any():
            continue
        X = X_all[mask].reset_index(drop=True)
        pred = model.predict(X)
        sub = feats[mask].reset_index(drop=True)
        share_col = MARKET_COLS[m][3]
        out.append(pd.DataFrame({"game_id": sub.game_id, "player_id": sub.player_id, "player_name": sub.player_name, "team": sub.team,
                                 "market": m, "mean_pre": pred["mean"].values, "sd_pre": pred["sd"].values,
                                 "share_pre": X[share_col].values if share_col else np.nan,
                                 "team_plays_pg": X["team_plays_pg"].values, "team_pass_rate": X["team_pass_rate"].values}))
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def replay_season(season: int = 2025, markets: list[str] | None = None, max_games: int | None = None) -> pd.DataFrame:
    markets = markets or list(MARKET_COLS)
    prior = _pregame_means(season, markets)
    if prior.empty:
        print("[replay] no priors"); return pd.DataFrame()
    prior_by_game = {g: d for g, d in prior.groupby("game_id")}
    pbp = db.read_sql("""SELECT game_id, play_id, posteam, defteam, home_team, away_team, qtr, game_seconds_remaining AS gsr,
                                play_type, pass, rush, qb_dropback, complete_pass, passing_yards, receiving_yards, rushing_yards,
                                passer_player_id, receiver_player_id, rusher_player_id, score_differential
                         FROM raw_pbp WHERE season=:s AND season_type='REG' AND posteam IS NOT NULL
                         ORDER BY game_id, play_id""", {"s": season})
    rows = []
    games = list(pbp.game_id.unique())[:max_games]
    for gid in games:
        g = pbp[pbp.game_id == gid]
        pri = prior_by_game.get(gid)
        if pri is None:
            continue
        real = g[g.play_type.isin(["pass", "run", "qb_kneel", "qb_spike"])]
        finals = {m: real.groupby(MARKET_COLS[m][1])[MARKET_COLS[m][0]].sum() for m in markets}
        for label, gsr_cut in CHECKPOINTS:
            sofar = real[real.gsr > gsr_cut]
            if sofar.empty:
                continue
            last = sofar.iloc[-1]
            secs_elapsed, secs_remaining = 3600 - gsr_cut, gsr_cut
            for team in (g.home_team.iloc[0], g.away_team.iloc[0]):
                tp = sofar[sofar.posteam == team]
                plays = int(len(tp)); pass_att = int(tp['pass'].fillna(0).sum()); rushes = int(tp.rush.fillna(0).sum())
                # score diff from this team's perspective at the checkpoint
                sd_last = float(last.score_differential) if pd.notna(last.score_differential) else 0.0
                score_diff = sd_last if last.posteam == team else -sd_last
                for pr in pri[pri.team == team].itertuples():
                    stat_col, pid_col, opp_col, _ = MARKET_COLS[pr.market]
                    mine = tp[tp[pid_col] == pr.player_id]
                    y_t = float(mine[stat_col].fillna(0).sum())
                    passing = pr.market != "player_rush_yds"
                    # opportunities counted the way ESPN's box score counts them: pass attempts (incl. sacks) / rushes
                    if pr.market == PASS_MARKET:
                        player_opps = int(mine['pass'].fillna(0).sum()); team_opps = pass_att
                    elif passing:
                        player_opps = int(len(mine)); team_opps = pass_att
                    else:
                        player_opps = int(len(mine)); team_opps = rushes
                    lp = project(pr.market, y_t, float(pr.mean_pre), float(pr.sd_pre), plays_so_far=plays, secs_elapsed=secs_elapsed,
                                 secs_remaining=secs_remaining, score_diff=score_diff, team_plays_pg=float(pr.team_plays_pg) if pd.notna(pr.team_plays_pg) else None,
                                 team_pass_rate=float(pr.team_pass_rate) if pd.notna(pr.team_pass_rate) else None,
                                 team_opps_so_far=team_opps, player_opps_so_far=player_opps,
                                 share_pre=float(pr.share_pre) if pd.notna(pr.share_pre) else (1.0 if pr.market == PASS_MARKET else None))
                    final = float(finals[pr.market].get(pr.player_id, 0.0))
                    rows.append({"game_id": gid, "player_id": pr.player_id, "player_name": pr.player_name, "market": pr.market, "checkpoint": label,
                                 "y_t": y_t, "f": lp.f, "usage_adj": lp.usage_adj, "script_adj": lp.script_adj, "remaining_share": lp.remaining_share,
                                 "live": lp.mean_live, "sd_live": lp.sd_live, "pregame": float(pr.mean_pre), "sd_pre": float(pr.sd_pre),
                                 "naive_pace": naive_pace(y_t, lp.f), "no_adj": y_t + float(pr.mean_pre) * (1 - lp.f), "final": final,
                                 "team_opps": team_opps, "player_opps": player_opps, "score_diff": score_diff})
    return pd.DataFrame(rows)


def summarize(res: pd.DataFrame) -> pd.DataFrame:
    if res.empty:
        return res
    r = res.copy()
    order = {c[0]: i for i, c in enumerate(CHECKPOINTS)}
    # players who actually played (a projected starter who was inactive is not an in-game-model question)
    r = r[(r.player_opps > 0) | (r.checkpoint == "end Q1")]
    out = []
    for (m, cp), g in r.groupby(["market", "checkpoint"]):
        row = {"market": m, "checkpoint": cp, "n": len(g)}
        for k in ("live", "pregame", "naive_pace", "no_adj"):
            row[f"mae_{k}"] = float((g[k] - g.final).abs().mean())
        # calibration of sd_live: share of finals inside ±1 sd (≈0.68 if calibrated) and the standardised error
        z = (g.final - g.live) / g.sd_live
        row["cover_1sd"] = float((z.abs() <= 1).mean()); row["z_sd"] = float(z.std())
        out.append(row)
    df = pd.DataFrame(out)
    return df.assign(_o=df.checkpoint.map(order)).sort_values(["market", "_o"]).drop(columns="_o")


def write_model_md(summary: pd.DataFrame, season: int, n_games: int):
    p = ROOT / "docs" / "MODEL.md"
    old = p.read_text() if p.exists() else ""
    marker = "\n# MODEL.md — live (in-game)"
    if marker in old:
        nxt = old.find("\n# MODEL.md — ", old.index(marker) + 1)
        old = old[:old.index(marker)] + (old[nxt:] if nxt != -1 else "")
    lines = [marker, "", f"_Replay of {season} play-by-play, {n_games} games, {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC. "
             "`python -m live replay`. Pre-game priors = the pipeline models on 2025 feature rows (held-out season)._", "",
             "MAE of the projected FINAL stat at each checkpoint. `live` = the in-game model (live/ingame.py); `pregame` = the pre-game mean; "
             "`naive_pace` = y_t / f; `no_adj` = y_t + (1−f)·mean (no usage / game-script adjustment). "
             "`cover_1sd` = share of finals within ±1 sd_live (0.68 if calibrated); `z_sd` = sd of the standardised error (1.0 if calibrated).", "",
             "| market | checkpoint | n | live | pregame | naive_pace | no_adj | cover_1sd | z_sd |", "|---|---|---|---|---|---|---|---|---|"]
    for r in summary.itertuples():
        lines.append(f"| {r.market} | {r.checkpoint} | {r.n} | **{r.mae_live:.1f}** | {r.mae_pregame:.1f} | {r.mae_naive_pace:.1f} | {r.mae_no_adj:.1f} | {r.cover_1sd:.2f} | {r.z_sd:.2f} |")
    lines += ["", "Reading: the live model should beat both baselines at every checkpoint and by a widening margin as the game goes on; "
              "`no_adj` vs `live` isolates what the usage and game-script terms add. If `z_sd` > 1 the live sd is too tight "
              "(raise LIVE_INGAME_SD_FLOOR); if < 1 it is too wide.", ""]
    p.write_text(old.rstrip("\n") + "\n" + "\n".join(lines))


def run(season: int = 2025, max_games: int | None = None, write: bool = True) -> pd.DataFrame:
    res = replay_season(season, max_games=max_games)
    s = summarize(res)
    if len(s):
        print(s.to_string(index=False, float_format=lambda x: f"{x:.2f}"))
        if write:
            write_model_md(s, season, res.game_id.nunique())
            res.to_parquet(ROOT / "pipeline" / "artifacts" / f"live_replay_{season}.parquet", index=False)
    return s
