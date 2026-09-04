"""Turn projections + the latest odds snapshot into cards (append-only).

For every (player, book, line) in the latest snapshot of the target week:
  model_prob  = P(side) from the projection distribution
  market_prob = that book's no-vig probability for the side
  edge        = model_prob − market_prob ;  ev = model_prob·(dec−1) − (1−model_prob)
One card per player-side: the (book, line) with the best EV. Published when
edge ≥ PUBLISH_MIN_EDGE and confidence ≥ PUBLISH_MIN_CONFIDENCE; everything is stored regardless.
"""
from __future__ import annotations
import json
import re
import numpy as np
import pandas as pd
from .. import db
from ..config import LEVEL_ANCHOR_W, PUBLISH_MIN_EDGE, PUBLISH_MIN_CONFIDENCE, MARKET_ANCHOR_W
from ..ingest.odds_jobs import target_week
from ..models.passing_yards import load_latest, MARKET
from ..sources.odds_api import american
from .factors import build_factors, confidence_score

LEAGUE_IMPLIED = 22.0


def _norm_name(s: str) -> str:
    s = re.sub(r"[^a-z ]", "", s.lower())
    s = re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", s)
    return " ".join(s.split())


def _latest_snapshot(season, week):
    r = db.read_sql("""SELECT id, taken_at FROM odds_snapshots WHERE season=:s AND week=:w
                       AND :m = ANY(markets) ORDER BY taken_at DESC LIMIT 1""", {"s": season, "w": week, "m": MARKET})
    return (int(r.id.iloc[0]), r.taken_at.iloc[0]) if len(r) else (None, None)


def _open_snapshot(season, week):
    r = db.read_sql("""SELECT id FROM odds_snapshots WHERE season=:s AND week=:w AND :m = ANY(markets)
                       ORDER BY taken_at ASC LIMIT 1""", {"s": season, "w": week, "m": MARKET})
    return int(r.id.iloc[0]) if len(r) else None


def score_week(week: int | None = None) -> int:
    season, wk = target_week()
    wk = week or wk
    model, run_id = load_latest()
    snap_id, snap_at = _latest_snapshot(season, wk)
    if snap_id is None:
        print(f"[score] no odds snapshot for {season} wk{wk}; nothing to score")
        return 0
    open_id = _open_snapshot(season, wk)

    with db.JobRun("score") as run:
        feats = db.read_sql("""SELECT f.*, g.home_team, g.away_team FROM feat_player_game f
                               JOIN raw_games g USING (game_id)
                               WHERE f.season=:s AND f.week=:w AND f.target_passing_yards IS NULL""",
                            {"s": season, "w": wk})
        if feats.empty:
            print("[score] no target-week feature rows; run build_features"); return 0
        X = pd.DataFrame([json.loads(f) if isinstance(f, str) else f for f in feats.features]).astype(float)
        pred = model.predict(X)
        feats = pd.concat([feats.reset_index(drop=True), pred], axis=1)
        feats["nname"] = feats.player_name.map(_norm_name)

        lines = db.read_sql("""SELECT l.*, e.game_id FROM odds_lines l JOIN odds_events e USING (event_id)
                               WHERE l.snapshot_id=:id AND l.market=:m""", {"id": snap_id, "m": MARKET})
        lines["nname"] = lines.player.map(_norm_name)
        open_lines = db.read_sql("""SELECT player, line, bookmaker FROM odds_lines WHERE snapshot_id=:id AND market=:m""",
                                 {"id": open_id, "m": MARKET}) if open_id else pd.DataFrame()
        injuries = db.read_sql("""SELECT DISTINCT ON (gsis_id) gsis_id, report_status, practice_status, report_primary_injury
                                  FROM raw_injuries WHERE season=:s AND week=:w ORDER BY gsis_id, observed_at DESC""",
                               {"s": season, "w": wk})
        inj_by_id = injuries.set_index("gsis_id").to_dict("index") if len(injuries) else {}
        wdf = db.read_sql("""SELECT DISTINCT ON (game_id) game_id, wind_mph, temp_f, precip_prob, is_dome
                             FROM raw_weather ORDER BY game_id, fetched_at DESC""").set_index("game_id")
        weather = {g: {k: (None if pd.isna(v) else v) for k, v in row.items()} for g, row in wdf.to_dict("index").items()}
        injury_data_available = bool(len(injuries))

        # league-level anchor: the median gap between posted lines and raw projections across every QB
        # this week is an *environment* disagreement (books price the season's passing level with
        # information the model lacks in Week 1-3), not a matchup one. Shift all projections by
        # LEVEL_ANCHOR_W of that gap, then apply the per-player anchor. Both are logged as a factor.
        cons = lines.groupby(["nname", "game_id"]).line.median().rename("cons_line").reset_index()
        gap = feats.merge(cons, on=["nname", "game_id"], how="inner")
        level_shift = float(LEVEL_ANCHOR_W * np.median(gap.cons_line - gap["mean"])) if len(gap) >= 8 else 0.0
        print(f"[score] level anchor: median line−model gap {np.median(gap.cons_line - gap['mean']) if len(gap) else 0:+.1f} → shift {level_shift:+.1f}")

        proj_rows, card_rows = [], []
        n_unmatched = 0
        for _, f in feats.iterrows():
            pl = lines[(lines.nname == f.nname) & (lines.game_id == f.game_id)]
            if pl.empty:
                n_unmatched += 1
                continue
            X_row = json.loads(f.features) if isinstance(f.features, str) else f.features
            # book-by-book two-way pricing
            books = []
            for (book, line), g in pl.groupby(["bookmaker", "line"]):
                o = g[g.side == "Over"]; u = g[g.side == "Under"]
                if o.empty or u.empty:
                    continue
                po, pu = 1 / o.price_decimal.iloc[0], 1 / u.price_decimal.iloc[0]
                books.append({"book": book, "line": float(line),
                              "over_dec": float(o.price_decimal.iloc[0]), "under_dec": float(u.price_decimal.iloc[0]),
                              "over_american": int(o.price_american.iloc[0]), "under_american": int(u.price_american.iloc[0]),
                              "over_fair": po / (po + pu), "under_fair": pu / (po + pu)})
            if not books:
                continue
            consensus_line = float(np.median([b["line"] for b in books]))
            raw_mean = float(f["mean"]) + level_shift
            used_mean = (1 - MARKET_ANCHOR_W) * raw_mean + MARKET_ANCHOR_W * consensus_line
            open_line = None
            if len(open_lines):
                ol = open_lines[open_lines.player.map(_norm_name) == f.nname]
                if len(ol):
                    open_line = float(ol.line.median())
            wx = weather.get(f.game_id)
            inj = inj_by_id.get(f.player_id)
            factors_ctx = dict(X=X_row, mean=raw_mean, used_mean=used_mean, sd=float(f["sd"]), line=consensus_line,
                               open_line=open_line, weather=wx, injury=inj, injury_data_available=injury_data_available,
                               opponent=f.opponent, team=f.team, is_home=bool(f.is_home))
            base_factors = build_factors(**factors_ctx)
            proj_rows.append({
                "model_run_id": run_id, "season": season, "week": wk, "game_id": f.game_id, "player_id": f.player_id,
                "player_name": f.player_name, "team": f.team, "opponent": f.opponent, "market": MARKET,
                "mean": float(f["mean"]), "sd": float(f["sd"]), "q10": float(f.q10), "q25": float(f.q25),
                "q50": float(f.q50), "q75": float(f.q75), "q90": float(f.q90),
                "factors": [x for x in base_factors if x["impact_over"] != 0 or x["factor"] in ("projection",)],
            })
            best = {}
            for b in books:
                p_over = float(model.p_over(used_mean, f["sd"], b["line"]))
                for side, mp, dec, am, fair in (("Over", p_over, b["over_dec"], b["over_american"], b["over_fair"]),
                                                ("Under", 1 - p_over, b["under_dec"], b["under_american"], b["under_fair"])):
                    ev = mp * (dec - 1) - (1 - mp)
                    cand = dict(side=side, model_prob=mp, market_prob=fair, edge=mp - fair, ev=ev, dec=dec,
                                american=am, book=b["book"], line=b["line"])
                    if side not in best or cand["ev"] > best[side]["ev"]:
                        best[side] = cand
            for side, c in best.items():
                if c["edge"] <= 0:
                    continue
                factors = [dict(x, impact=("+" if x["impact_over"] * (1 if side == "Over" else -1) > 0
                                           else "−" if x["impact_over"] * (1 if side == "Over" else -1) < 0 else "▬"))
                           for x in base_factors]
                factors.sort(key=lambda x: -abs(x.get("magnitude", 0)))
                conf = confidence_score(X_row, c, open_line, wx, inj, injury_data_available, len(books), side)
                card_rows.append({
                    "season": season, "week": wk, "game_id": f.game_id,
                    "event_id": pl.event_id.iloc[0], "player_id": f.player_id, "player_name": f.player_name,
                    "position": "QB", "team": f.team, "opponent": f.opponent, "kickoff_utc": f.kickoff_utc,
                    "market": MARKET, "side": side, "line": c["line"], "price_american": int(c["american"]),
                    "price_decimal": c["dec"], "book": c["book"], "snapshot_id": snap_id, "model_run_id": run_id,
                    "model_prob": c["model_prob"], "market_prob": c["market_prob"], "edge": c["edge"],
                    "ev_per_unit": c["ev"], "confidence": int(conf), "score": c["edge"] * conf,
                    "published": bool(c["edge"] >= PUBLISH_MIN_EDGE and conf >= PUBLISH_MIN_CONFIDENCE),
                    "factors": factors, "line_open": open_line, "line_open_snapshot_id": open_id,
                    "book_prices": [{"book": b["book"], "line": b["line"], "over": b["over_american"], "under": b["under_american"]} for b in books],
                    "_proj_idx": len(proj_rows) - 1,
                })

        # persist projections, then cards referencing them
        proj_df = pd.DataFrame(proj_rows)
        ids = []
        for r in proj_df.to_dict("records"):
            ids.append(db.insert_returning_id("projections", r))
        for c in card_rows:
            c["projection_id"] = ids[c.pop("_proj_idx")]
        n = db.append(pd.DataFrame(card_rows), "cards") if card_rows else 0
        n_pub = sum(c["published"] for c in card_rows)
        run.rows = n
        run.detail = {"season": season, "week": wk, "snapshot_id": snap_id, "projections": len(ids),
                      "cards": n, "published": n_pub, "unmatched_players": n_unmatched}
        print(f"[score] {season} wk{wk}: {len(ids)} projections, {n} cards, {n_pub} published, {n_unmatched} QBs without lines")
        return n
