"""Moneyline scoring → game_projections (every game) + cards (append-only).

p_used = (1 − w)·p_model + w·p_books  with w = anchor weight chosen on validation (≈0.95).
market_prob for a card = the venue's own implied probability (with vig) at the price you'd get, so
edge = p_used − 1/decimal. A card therefore flags venues priced better than the sharp consensus —
in practice Polymarket vs books, or one book off-market — rather than model-vs-market disagreement
(which the backtest in MODEL.md shows loses money).

Polymarket prices are mid quotes; we haircut them by POLY_SPREAD (1.5¢) to approximate the ask.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from .. import db
from ..config import PUBLISH_MIN_EDGE_ML as PUBLISH_MIN_EDGE, PUBLISH_MIN_CONFIDENCE
from ..ingest.odds_jobs import target_week
from ..features.team_ratings import game_features
from ..models.moneyline import load_latest, MARKET
from ..teams import ABBR_TO_NAME
from .factors import TEAM_NAMES, _ord

POLY_SPREAD = 0.015


def _american(dec: float) -> int:
    return int(round((dec - 1) * 100)) if dec >= 2 else int(round(-100 / (dec - 1)))


def score_moneylines(week: int | None = None) -> int:
    season, wk = target_week()
    wk = week or wk
    model, run_id = load_latest()
    snap = db.read_sql("""SELECT id FROM odds_snapshots WHERE season=:s AND week=:w AND 'h2h' = ANY(markets)
                          ORDER BY taken_at DESC LIMIT 1""", {"s": season, "w": wk})
    if snap.empty:
        print("[score-ml] no snapshot"); return 0
    snap_id = int(snap.id.iloc[0])
    with db.JobRun("score_ml") as run:
        f = game_features([season])
        f = f[(f.week == wk) & f.home_win.isna()].copy()
        if f.empty:
            print("[score-ml] no upcoming games"); return 0
        f["p_model"] = model.predict_home(f)
        lines = db.read_sql("""SELECT l.*, e.game_id FROM odds_lines l JOIN odds_events e USING (event_id)
                               WHERE l.snapshot_id=:id AND l.market='h2h'""", {"id": snap_id})
        # Elo ranks for factor text
        elo_rank = {}
        allf = pd.concat([f[["home_team", "elo_home"]].rename(columns={"home_team": "t", "elo_home": "e"}),
                          f[["away_team", "elo_away"]].rename(columns={"away_team": "t", "elo_away": "e"})]).drop_duplicates("t")
        for rk, (_, r) in enumerate(allf.sort_values("e", ascending=False).iterrows(), 1):
            elo_rank[r.t] = rk

        proj_rows, card_rows = [], []
        for _, g in f.iterrows():
            gl = lines[lines.game_id == g.game_id]
            home_name, away_name = ABBR_TO_NAME[g.home_team], ABBR_TO_NAME[g.away_team]
            books, poly = {}, None
            for bk, d in gl.groupby("bookmaker"):
                h = d[d.side == home_name]; a = d[d.side == away_name]
                if h.empty or a.empty:
                    continue
                dh, da = float(h.price_decimal.iloc[0]), float(a.price_decimal.iloc[0])
                if bk == "polymarket":
                    poly = {"dec_home": dh, "dec_away": da, "p_home": (1 / dh) / (1 / dh + 1 / da)}
                else:
                    ih, ia = 1 / dh, 1 / da
                    books[bk] = {"dec_home": dh, "dec_away": da, "p_home": ih / (ih + ia)}
            p_books = float(np.mean([b["p_home"] for b in books.values()])) if books else None
            p_poly = poly["p_home"] if poly else None
            p_used = (1 - model.anchor_w) * g.p_model + model.anchor_w * p_books if p_books is not None else float(g.p_model)

            # venues (books at their price, Polymarket at mid − spread)
            venues = {bk: (b["dec_home"], b["dec_away"]) for bk, b in books.items()}
            if poly:
                venues["polymarket"] = (1 / (1 / poly["dec_home"] + POLY_SPREAD), 1 / (1 / poly["dec_away"] + POLY_SPREAD))
            best = {}
            for side, p_side, idx in ((g.home_team, p_used, 0), (g.away_team, 1 - p_used, 1)):
                for bk, decs in venues.items():
                    dec = decs[idx]
                    ev = p_side * (dec - 1) - (1 - p_side)
                    cand = {"book": bk, "dec": dec, "american": _american(dec), "market_prob": 1 / dec,
                            "model_prob": p_side, "edge": p_side - 1 / dec, "ev": ev}
                    if side not in best or cand["ev"] > best[side]["ev"]:
                        best[side] = cand

            factors = _factors(g, elo_rank, p_books, p_poly, p_used, books, poly, model.anchor_w)
            proj_rows.append({
                "model_run_id": run_id, "season": season, "week": wk, "game_id": g.game_id, "snapshot_id": snap_id,
                "home_team": g.home_team, "away_team": g.away_team, "kickoff_utc": g.kickoff_utc,
                "p_home_model": float(g.p_model), "p_home_market": p_books, "p_home_polymarket": p_poly,
                "p_home_used": p_used, "elo_home": float(g.elo_home), "elo_away": float(g.elo_away),
                "home_best": {k: v for k, v in best.get(g.home_team, {}).items() if k in ("book", "american", "dec")},
                "away_best": {k: v for k, v in best.get(g.away_team, {}).items() if k in ("book", "american", "dec")},
                "factors": factors,
            })
            for side, c in best.items():
                if c["edge"] <= 0:
                    continue
                is_home = side == g.home_team
                conf = _confidence(g, c, is_home, books, poly, wk)
                sf = [dict(x, impact=_impact(x, is_home)) for x in factors]
                sf.sort(key=lambda x: -abs(x.get("magnitude", 0)))
                card_rows.append({
                    "season": season, "week": wk, "game_id": g.game_id,
                    "event_id": gl.event_id.iloc[0] if len(gl) else None,
                    "player_id": None, "player_name": ABBR_TO_NAME[side], "position": "TEAM",
                    "team": side, "opponent": g.away_team if is_home else g.home_team, "kickoff_utc": g.kickoff_utc,
                    "market": MARKET, "side": side, "line": None, "price_american": c["american"],
                    "price_decimal": c["dec"], "book": c["book"], "snapshot_id": snap_id, "model_run_id": run_id,
                    "model_prob": c["model_prob"], "market_prob": c["market_prob"], "edge": c["edge"],
                    "ev_per_unit": c["ev"], "confidence": conf, "score": c["edge"] * conf,
                    "published": bool(c["edge"] >= PUBLISH_MIN_EDGE and conf >= PUBLISH_MIN_CONFIDENCE),
                    "factors": sf, "line_open": None,
                    "book_prices": [{"book": bk, "home": _american(d[0]), "away": _american(d[1])} for bk, d in venues.items()],
                })
        db.append(pd.DataFrame(proj_rows), "game_projections")
        n = db.append(pd.DataFrame(card_rows), "cards") if card_rows else 0
        run.rows = n
        run.detail = {"games": len(proj_rows), "cards": n, "published": int(sum(c["published"] for c in card_rows))}
        print(f"[score-ml] {season} wk{wk}: {len(proj_rows)} games, {n} cards, {run.detail['published']} published")
        return n


def _impact(x: dict, is_home: bool) -> str:
    v = x.get("impact_home", 0) * (1 if is_home else -1)
    return "+" if v > 0 else "−" if v < 0 else "▬"


def _factors(g, elo_rank, p_books, p_poly, p_used, books, poly, w) -> list[dict]:
    H, A = TEAM_NAMES[g.home_team], TEAM_NAMES[g.away_team]
    F = []
    d = float(g.elo_diff)
    F.append({"factor": "elo", "value": round(d), "impact_home": 1 if d > 25 else -1 if d < -25 else 0,
              "magnitude": min(abs(d) / 150, 1),
              "text": f"Elo: {H} {g.elo_home:.0f} ({_ord(elo_rank.get(g.home_team, 0))}) vs {A} {g.elo_away:.0f} ({_ord(elo_rank.get(g.away_team, 0))}); home field worth ~48 pts",
              "source": {"table": "game_projections", "key": "elo_home"}})
    e = float(g.epa_diff) if pd.notna(g.epa_diff) else 0.0
    F.append({"factor": "epa_rating", "value": round(e, 3), "impact_home": 1 if e > 0.04 else -1 if e < -0.04 else 0,
              "magnitude": min(abs(e) / 0.15, 1) * 0.8,
              "text": f"EPA rating (offense − defense allowed): {H} {float(g.home_off_epa or 0) - float(g.home_def_epa or 0):+.3f} vs {A} {float(g.away_off_epa or 0) - float(g.away_def_epa or 0):+.3f} per play",
              "source": {"table": "feat_team_offense", "key": "epa_per_play"}})
    if pd.notna(g.rest_diff) and abs(g.rest_diff) >= 3:
        F.append({"factor": "rest", "value": float(g.rest_diff), "impact_home": 1 if g.rest_diff > 0 else -1,
                  "magnitude": min(abs(g.rest_diff) / 7, 1) * 0.4,
                  "text": f"Rest: {H} {int(g.home_rest)} days vs {A} {int(g.away_rest)} days",
                  "source": {"table": "raw_games", "key": "home_rest"}})
    for team, chg, starts, name, sign in ((g.home_team, g.home_qb_change, g.home_qb_starts, H, -1), (g.away_team, g.away_qb_change, g.away_qb_starts, A, 1)):
        if chg == 1:
            F.append({"factor": "qb_change", "value": team, "impact_home": sign, "magnitude": 0.5,
                      "text": f"{name} start a different QB than last game ({int(starts or 0)} prior NFL starts)",
                      "source": {"table": "raw_depth_charts", "key": "QB1"}})
    if g.div_game == 1:
        F.append({"factor": "divisional", "value": 1, "impact_home": 0, "magnitude": 0.1, "text": "Divisional game",
                  "source": {"table": "raw_games", "key": "div_game"}})
    if p_books is not None:
        F.append({"factor": "market", "value": round(p_books, 3), "impact_home": 0, "magnitude": 0.2,
                  "text": f"Sportsbook consensus (no-vig, {len(books)} books): {H} {p_books:.1%} · {A} {1 - p_books:.1%}",
                  "source": {"table": "odds_consensus", "key": "over_consensus_prob"}})
    F.append({"factor": "model_vs_market", "value": round(float(g.p_model), 3), "impact_home": 0, "magnitude": 0.3,
              "text": f"Ratings model alone: {H} {g.p_model:.1%}; blended {int(w * 100)}% toward the market → {p_used:.1%} (the raw model loses vs closing lines — see MODEL.md)",
              "source": {"table": "model_runs", "key": "metrics"}})
    if p_poly is not None and p_books is not None:
        diff = p_poly - p_books
        F.append({"factor": "polymarket", "value": round(p_poly, 3), "impact_home": 1 if diff < -0.02 else -1 if diff > 0.02 else 0,
                  "magnitude": min(abs(diff) / 0.08, 1) * 0.7,
                  "text": f"Polymarket prices {H} at {p_poly:.1%} vs books {p_books:.1%} ({diff:+.1%}) — "
                          + ("traders cheaper on the " + (A if diff < 0 else H) if abs(diff) >= 0.02 else "in line with books"),
                  "source": {"table": "odds_lines", "key": "polymarket"}})
    if books:
        bh = max(books.items(), key=lambda kv: kv[1]["dec_home"]); ba = max(books.items(), key=lambda kv: kv[1]["dec_away"])
        F.append({"factor": "price_shop", "value": None, "impact_home": 0, "magnitude": 0.15,
                  "text": f"Best book price: {H} {_american(bh[1]['dec_home']):+d} ({bh[0]}) · {A} {_american(ba[1]['dec_away']):+d} ({ba[0]})",
                  "source": {"table": "odds_lines", "key": "price_decimal"}})
    return F


def _confidence(g, c, is_home, books, poly, wk) -> int:
    conf = 70.0
    if (g.home_qb_change == 1) or (g.away_qb_change == 1):
        conf -= 8
    if wk <= 3:
        conf -= 8
    if c["book"] == "polymarket":
        conf -= 10          # mid-price liquidity risk
    if len(books) < 3:
        conf -= 6
    if c["edge"] > 0.08:
        conf -= 15          # big moneyline gaps are model error far more often than value (MODEL.md)
    elif c["edge"] > 0.04:
        conf -= 5
    return int(max(0, min(100, round(conf))))
