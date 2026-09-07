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
from ..config import LEVEL_ANCHOR_W, PUBLISH_MIN_EDGE_BY_MARKET, PUBLISH_MIN_EDGE_PROPS, PUBLISH_MIN_CONFIDENCE, MARKET_ANCHOR_W, NON_BETTABLE_BOOKS, SHARP_BOOK, is_bettable
from ..ingest.odds_jobs import target_week
from ..models.passing_yards import load_latest as load_latest_py, MARKET as PASS_MARKET
from ..models.player_props import load_latest as load_latest_prop, SPECS
from ..sources.odds_api import american
from .factors import build_factors, confidence_score
from .skill_factors import build_skill_factors, skill_confidence
from ..models.calibration import load_latest as load_calibrator, featurize as cal_featurize

LEAGUE_IMPLIED = 22.0


def _norm_name(s: str) -> str:
    s = re.sub(r"[^a-z ]", "", s.lower())
    s = re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", s)
    return " ".join(s.split())


def _latest_snapshot(season, week, market):
    r = db.read_sql("""SELECT id, taken_at FROM odds_snapshots WHERE season=:s AND week=:w
                       AND :m = ANY(markets) ORDER BY taken_at DESC LIMIT 1""", {"s": season, "w": week, "m": market})
    return (int(r.id.iloc[0]), r.taken_at.iloc[0]) if len(r) else (None, None)


def _open_snapshot(season, week, market):
    r = db.read_sql("""SELECT id FROM odds_snapshots WHERE season=:s AND week=:w AND :m = ANY(markets)
                       ORDER BY taken_at ASC LIMIT 1""", {"s": season, "w": week, "m": market})
    return int(r.id.iloc[0]) if len(r) else None


def score_all(week: int | None = None) -> int:
    """Score every prop market that has a trained model and a snapshot."""
    total = 0
    for m in [PASS_MARKET] + list(SPECS):
        try:
            total += score_week(week, m)
        except RuntimeError as e:   # no model yet for a market → skip, never crash the run
            print(f"[score:{m}] skipped: {e}")
    return total


def score_week(week: int | None = None, market: str = PASS_MARKET) -> int:
    MARKET = market
    PUBLISH_MIN_EDGE = PUBLISH_MIN_EDGE_BY_MARKET.get(market, PUBLISH_MIN_EDGE_PROPS)
    season, wk = target_week()
    wk = week or wk
    is_qb = market == PASS_MARKET
    if is_qb:
        model, run_id = load_latest_py()
    else:
        model, run_id = load_latest_prop(market)
    spec = None if is_qb else SPECS[market]
    snap_id, snap_at = _latest_snapshot(season, wk, MARKET)
    if snap_id is None:
        print(f"[score:{market}] no odds snapshot for {season} wk{wk}; nothing to score")
        return 0
    calibrator = load_calibrator()   # None until `train_cal` has run; cards then carry raw edge only
    open_id = _open_snapshot(season, wk, MARKET)

    with db.JobRun(f"score:{market}") as run:
        if is_qb:
            feats = db.read_sql("""SELECT f.*, g.home_team, g.away_team FROM feat_player_game f
                                   JOIN raw_games g USING (game_id)
                                   WHERE f.season=:s AND f.week=:w AND f.position='QB' AND f.target_passing_yards IS NULL""",
                                {"s": season, "w": wk})
        else:
            feats = db.read_sql("""SELECT f.*, g.home_team, g.away_team FROM feat_player_game f
                                   JOIN raw_games g USING (game_id)
                                   WHERE f.season=:s AND f.week=:w AND f.position = ANY(:p) AND f.target_targets IS NULL""",
                                {"s": season, "w": wk, "p": list(spec.positions)})
        if feats.empty:
            print("[score] no target-week feature rows; run build_features"); return 0
        X = pd.DataFrame([json.loads(f) if isinstance(f, str) else f for f in feats.features]).astype(float)
        if spec is not None:   # eligibility: same usage floor as training
            ok = X[spec.min_usage].fillna(0) >= spec.min_usage_val
            feats, X = feats[ok.values].reset_index(drop=True), X[ok.values].reset_index(drop=True)
            if feats.empty:
                print(f"[score:{market}] no eligible players"); return 0
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
        # anchors operate on the model MEDIAN (books deal a median line); the mean moves by the same amount
        cons = lines.groupby(["nname", "game_id"]).line.median().rename("cons_line").reset_index()
        gap = feats.merge(cons, on=["nname", "game_id"], how="inner")
        level_shift = float(LEVEL_ANCHOR_W * np.median(gap.cons_line - gap["q50"])) if len(gap) >= 8 else 0.0
        print(f"[score:{market}] level anchor: median line−model-median gap {np.median(gap.cons_line - gap['q50']) if len(gap) else 0:+.1f} → shift {level_shift:+.1f}")

        proj_rows, card_rows = [], []
        n_unmatched = 0
        for _, f in feats.iterrows():
            pl = lines[(lines.nname == f.nname) & (lines.game_id == f.game_id)]
            if pl.empty:
                n_unmatched += 1
                continue
            X_row = json.loads(f.features) if isinstance(f.features, str) else f.features
            # book-by-book two-way pricing (bettable US books); the sharp reference book is kept separately
            books, sharp = [], None
            for (book, line), g in pl.groupby(["bookmaker", "line"]):
                o = g[g.side == "Over"]; u = g[g.side == "Under"]
                if o.empty or u.empty:
                    continue
                po, pu = 1 / o.price_decimal.iloc[0], 1 / u.price_decimal.iloc[0]
                row = {"book": book, "line": float(line),
                       "over_dec": float(o.price_decimal.iloc[0]), "under_dec": float(u.price_decimal.iloc[0]),
                       "over_american": int(o.price_american.iloc[0]), "under_american": int(u.price_american.iloc[0]),
                       "over_fair": po / (po + pu), "under_fair": pu / (po + pu)}
                if book == SHARP_BOOK and (sharp is None or abs(row["over_dec"] - row["under_dec"]) < abs(sharp["over_dec"] - sharp["under_dec"])):
                    sharp = row   # the sharp reference: its main line = the alternate priced closest to even money
                if not is_bettable(book):
                    continue
                books.append(row)
            if not books:
                continue
            consensus_line = float(np.median([b["line"] for b in books]))
            q50_lvl = float(f["q50"]) + level_shift
            q50_used = (1 - MARKET_ANCHOR_W) * q50_lvl + MARKET_ANCHOR_W * consensus_line
            raw_mean = float(f["mean"]) + level_shift
            used_mean = float(f["mean"]) + (q50_used - float(f["q50"]))
            q_shift = q50_used - float(f["q50"])
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
            base_factors = build_factors(**factors_ctx) if is_qb else build_skill_factors(market=market, position=f.position, **factors_ctx)
            sharp_diff = None
            if sharp is not None:
                sharp_diff = sharp["line"] - consensus_line     # >0: the sharp book expects MORE than the US books
                unit = 0.5 if market == "player_receptions" else 1.0
                # Pinnacle's own lean at its line (no-vig over prob) sharpens the read when the lines match
                lean = sharp["over_fair"] - 0.5
                imp = 1 if sharp_diff >= unit or (abs(sharp_diff) < unit and lean >= 0.02) else (-1 if sharp_diff <= -unit or (abs(sharp_diff) < unit and lean <= -0.02) else 0)
                base_factors.insert(0, {"factor": "sharp_line", "value": round(sharp_diff, 1), "impact_over": imp,
                                        "magnitude": min(abs(sharp_diff) / (unit * 4), 1) * 0.8 + 0.1,
                                        "text": f"Pinnacle (sharp) line {sharp['line']:g} at {american(sharp['over_dec'])}/{american(sharp['under_dec'])} vs US consensus {consensus_line:g}"
                                                + (f" — sharp market {'higher' if sharp_diff > 0 else 'lower'} by {abs(sharp_diff):g}" if abs(sharp_diff) >= unit else " — agrees with the US books"),
                                        "source": {"table": "odds_lines", "key": "pinnacle"}})
            proj_rows.append({
                "model_run_id": run_id, "season": season, "week": wk, "game_id": f.game_id, "player_id": f.player_id,
                "player_name": f.player_name, "team": f.team, "opponent": f.opponent, "market": MARKET,
                # quantiles are stored AFTER the level/market anchoring so the card's chart matches the probability used
                "mean": float(f["mean"]), "sd": float(f["sd"]), "q10": float(f.q10) + q_shift, "q25": float(f.q25) + q_shift,
                "q50": float(f.q50) + q_shift, "q75": float(f.q75) + q_shift, "q90": float(f.q90) + q_shift,
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
                # the bottom line first: the matchup/context factors are what the book already priced into the line;
                # the pick is the gap between our (anchored) median and that line
                gap = q50_used - float(c["line"])
                unit_txt = "" if market == "player_receptions" else " yds"
                factors.insert(0, {"factor": "bottom_line", "value": round(gap, 1), "impact_over": 1 if gap > 0 else -1,
                                   "magnitude": min(abs(gap) / max(float(f["sd"]), 1e-6) * 2, 1.0),
                                   "impact": "+" if (gap > 0) == (side == "Over") else "−",
                                   "text": f"Bottom line: our median {q50_used:.0f} vs line {c['line']:g} ({gap:+.1f}{unit_txt}, {abs(gap) / max(float(f['sd']), 1e-6):.2f} sd). "
                                           f"The opponent and game factors below are already priced into the line — the pick is that the book "
                                           f"{'under' if gap > 0 else 'over'}shoots the player's usage-based projection.",
                                   "source": {"table": "projections", "key": "q50"}})
                conf = (confidence_score(X_row, c, open_line, wx, inj, injury_data_available, len(books), side) if is_qb
                        else skill_confidence(X_row, c, open_line, wx, inj, injury_data_available, len(books), side, market))
                sf = 0
                if sharp_diff is not None:
                    # the sharpest book agreeing with the pick's direction is worth something; disagreeing costs more
                    sf = base_factors[0]["impact_over"] * (1 if side == "Over" else -1)
                    conf = int(max(0, min(100, conf + (4 if sf > 0 else -6 if sf < 0 else 0))))
                p_cal, edge_cal = None, None
                if calibrator is not None:
                    row = cal_featurize(market, float(c["edge"]), used_mean, float(f["sd"]), float(c["line"]), side, X_row, sf, float(c["market_prob"]))
                    p_cal = float(calibrator.p_win([row])[0])
                    edge_cal = p_cal - float(c["market_prob"])
                card_rows.append({
                    "season": season, "week": wk, "game_id": f.game_id,
                    "event_id": pl.event_id.iloc[0], "player_id": f.player_id, "player_name": f.player_name,
                    "position": f.position, "team": f.team, "opponent": f.opponent, "kickoff_utc": f.kickoff_utc,
                    "market": MARKET, "side": side, "line": c["line"], "price_american": int(c["american"]),
                    "price_decimal": c["dec"], "book": c["book"], "snapshot_id": snap_id, "model_run_id": run_id,
                    "model_prob": c["model_prob"], "market_prob": c["market_prob"], "edge": c["edge"],
                    "ev_per_unit": c["ev"], "confidence": int(conf), "score": c["edge"] * conf,
                    "prob_calibrated": p_cal, "edge_calibrated": edge_cal,
                    "published": bool(c["edge"] >= PUBLISH_MIN_EDGE and conf >= PUBLISH_MIN_CONFIDENCE),
                    "factors": factors, "line_open": open_line, "line_open_snapshot_id": open_id,
                    "book_prices": [{"book": b["book"], "line": b["line"], "over": b["over_american"], "under": b["under_american"]} for b in books]
                                   + ([{"book": sharp["book"], "line": sharp["line"], "over": sharp["over_american"], "under": sharp["under_american"]}]
                                      if sharp and not any(b["book"] == sharp["book"] and b["line"] == sharp["line"] for b in books) else []),
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
        print(f"[score:{market}] {season} wk{wk}: {len(ids)} projections, {n} cards, {n_pub} published, {n_unmatched} players without lines")
        return n
