"""Spread scoring → spread_projections (every game, Sasser-layout fields) + cards(market='spreads', append-only).

For each upcoming game in the target week:
  proj_margin_raw   ratings model alone (home perspective)
  proj_margin       blended toward the current market spread with the anchor weight from MODEL.md
  proj_total        same for the total → projected scores home=(total+margin)/2, away=(total−margin)/2
  open / current    consensus spread (median of the bettable books' home handicap) at the week's first and
                    latest snapshot; Pinnacle is the reference for P(cover) when it is present
  pick              the side the projection favours vs the CURRENT line, at that side's best bettable price
  p_cover / edge    empirical P(cover) from the model's walk-forward residuals vs the book's implied probability

A card is written for every pick so the model's every-game ATS record is graded like everything else, but it is
NOT published as a bet: the closing-line backtest (MODEL.md) shows a ratings model does not beat NFL spreads
except, weakly, at ≥5-pt disagreements — too thin to stake. Picks are shown on /games as leans with the gap.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from .. import db
from ..config import is_bettable, SHARP_BOOK
from ..ingest.odds_jobs import target_week
from ..features.team_ratings import game_features
from ..models.spread import load_latest, MARKET, _prep
from ..teams import ABBR_TO_NAME
from .factors import TEAM_NAMES, _ord

FLAG_GAP = 5.0   # raw-model gap (pts) above which the pick is marked "lean+" (backtest: 75-63 ATS, +3.7% ROI, n=139 — not stakeable)


def _american(dec: float) -> int:
    return int(round((dec - 1) * 100)) if dec >= 2 else int(round(-100 / (dec - 1)))


def _consensus(gl: pd.DataFrame, home_name: str, books_only: bool = True) -> tuple[float | None, float | None]:
    """(median home spread across bettable books, Pinnacle home spread or None)."""
    h = gl[(gl.side == home_name)]
    if books_only:
        h = h[h.bookmaker.map(is_bettable) | (h.bookmaker == SHARP_BOOK)]
    if h.empty:
        return None, None
    sharp = h[h.bookmaker == SHARP_BOOK]
    med = float(h[h.bookmaker.map(is_bettable)].line.median()) if h.bookmaker.map(is_bettable).any() else float(h.line.median())
    return med, (float(sharp.line.iloc[0]) if len(sharp) else None)


def score_spreads(week: int | None = None) -> int:
    season, wk = target_week()
    wk = week or wk
    model, run_id = load_latest()
    snaps = db.read_sql("""SELECT id, taken_at FROM odds_snapshots WHERE season=:s AND week=:w AND 'spreads' = ANY(markets)
                           ORDER BY taken_at""", {"s": season, "w": wk})
    if snaps.empty:
        print("[score-spread] no snapshot"); return 0
    open_id, snap_id = int(snaps.id.iloc[0]), int(snaps.id.iloc[-1])
    with db.JobRun("score_spreads") as run:
        f = _prep(game_features([season]))
        f = f[(f.week == wk) & f.home_win.isna()].copy()
        if f.empty:
            print("[score-spread] no upcoming games"); return 0
        f["m_raw"] = model.predict_margin(f)
        f["t_raw"] = model.predict_total(f)
        lines = db.read_sql("""SELECT l.*, e.game_id FROM odds_lines l JOIN odds_events e USING (event_id)
                               WHERE l.snapshot_id IN (:a, :b) AND l.market IN ('spreads', 'totals')""", {"a": open_id, "b": snap_id})
        rec = _records(season, wk)
        proj_rows, card_rows = [], []
        for _, g in f.iterrows():
            H, A = ABBR_TO_NAME[g.home_team], ABBR_TO_NAME[g.away_team]
            cur = lines[(lines.game_id == g.game_id) & (lines.snapshot_id == snap_id)]
            opn = lines[(lines.game_id == g.game_id) & (lines.snapshot_id == open_id)]
            cur_sp, cur_pin = _consensus(cur[cur.market == "spreads"], H)
            open_sp, _ = _consensus(opn[opn.market == "spreads"], H)
            tot_rows = cur[(cur.market == "totals") & (cur.side == "Over") & cur.bookmaker.map(is_bettable)]
            cur_tot = float(tot_rows.line.median()) if len(tot_rows) else None
            ref_sp = cur_pin if cur_pin is not None else cur_sp
            # nflverse convention: spread_line = expected HOME margin; book handicap for the home side is its negative
            mkt_margin = -ref_sp if ref_sp is not None else None
            m_used = (1 - model.anchor_w) * g.m_raw + model.anchor_w * mkt_margin if mkt_margin is not None else float(g.m_raw)
            t_used = (1 - model.total_anchor_w) * g.t_raw + model.total_anchor_w * cur_tot if cur_tot is not None else float(g.t_raw)
            # projected scores and the pick come from the RAW model (Sasser-style: the model's own number against the
            # line in every game); the blend is stored and shown alongside. P(cover) uses the raw model's residuals.
            home_pts, away_pts = (g.t_raw + g.m_raw) / 2, (g.t_raw - g.m_raw) / 2
            gap_raw = float(g.m_raw - mkt_margin) if mkt_margin is not None else None      # >0 → model likes home more
            gap_used = float(m_used - mkt_margin) if mkt_margin is not None else None
            pick, card = None, None
            if mkt_margin is not None and gap_raw != 0:
                side = g.home_team if gap_raw > 0 else g.away_team
                side_name = H if gap_raw > 0 else A
                cand = cur[(cur.market == "spreads") & (cur.side == side_name) & cur.bookmaker.map(is_bettable)]
                if len(cand):
                    # best price at the consensus handicap for that side (or the closest handicap); prefer better line then price
                    side_line = -cur_sp if gap_raw > 0 else cur_sp
                    cand = cand.assign(dl=(cand.line - side_line).abs()).sort_values(["dl", "price_decimal"], ascending=[True, False])
                    b = cand.iloc[0]
                    line_side = float(b.line)                          # handicap from the picked side's perspective
                    p_cover = float(model.p_home_cover(np.array([g.m_raw]), np.array([-line_side]))[0]) if gap_raw > 0 \
                        else float(1 - model.p_home_cover(np.array([g.m_raw]), np.array([line_side]))[0])
                    dec = float(b.price_decimal)
                    pick = {"side": side, "line": line_side, "book": b.bookmaker, "american": int(b.price_american), "dec": dec,
                            "p_cover": p_cover, "market_prob": 1 / dec, "edge": p_cover - 1 / dec}
            proj_rows.append({
                "model_run_id": run_id, "season": season, "week": wk, "game_id": g.game_id, "snapshot_id": snap_id,
                "open_snapshot_id": open_id, "home_team": g.home_team, "away_team": g.away_team, "kickoff_utc": g.kickoff_utc,
                "home_record": rec.get(g.home_team, "0-0"), "away_record": rec.get(g.away_team, "0-0"),
                "proj_margin_raw": float(g.m_raw), "proj_margin": float(m_used), "proj_total_raw": float(g.t_raw), "proj_total": float(t_used),
                "proj_home_score": float(home_pts), "proj_away_score": float(away_pts),   # raw model
                "open_spread": open_sp, "current_spread": cur_sp, "sharp_spread": cur_pin, "current_total": cur_tot,
                "gap_raw": gap_raw, "gap": gap_used,
                "pick_side": pick["side"] if pick else None, "pick_line": pick["line"] if pick else None,
                "pick_book": pick["book"] if pick else None, "pick_price_american": pick["american"] if pick else None,
                "pick_p_cover": pick["p_cover"] if pick else None, "pick_edge": pick["edge"] if pick else None,
                "lean_plus": bool(gap_raw is not None and abs(gap_raw) >= FLAG_GAP and pick),
                "factors": _factors(g, m_used, mkt_margin, cur_pin is not None, model.anchor_w, open_sp, cur_sp),
            })
            if pick:
                is_home = pick["side"] == g.home_team
                card_rows.append({
                    "season": season, "week": wk, "game_id": g.game_id,
                    "event_id": cur.event_id.iloc[0] if len(cur) else None,
                    "player_id": None, "player_name": ABBR_TO_NAME[pick["side"]], "position": "TEAM",
                    "team": pick["side"], "opponent": g.away_team if is_home else g.home_team, "kickoff_utc": g.kickoff_utc,
                    "market": MARKET, "side": pick["side"], "line": pick["line"], "price_american": pick["american"],
                    "price_decimal": pick["dec"], "book": pick["book"], "snapshot_id": snap_id, "model_run_id": run_id,
                    "model_prob": pick["p_cover"], "market_prob": pick["market_prob"], "edge": pick["edge"],
                    "ev_per_unit": pick["p_cover"] * (pick["dec"] - 1) - (1 - pick["p_cover"]),
                    "confidence": 40, "score": pick["edge"] * 40,
                    "published": False,          # leans only — see module docstring / DECISIONS #40
                    "factors": [dict(x, impact=("+" if x.get("impact_home", 0) * (1 if is_home else -1) > 0 else "−" if x.get("impact_home", 0) * (1 if is_home else -1) < 0 else "▬")) for x in proj_rows[-1]["factors"]],
                    "line_open": (-open_sp if is_home else open_sp) if open_sp is not None else None,
                    "book_prices": [{"book": bk, "line": float(d.line.iloc[0]), "american": int(d.price_american.iloc[0])}
                                    for bk, d in cur[(cur.market == "spreads") & (cur.side == ABBR_TO_NAME[pick["side"]])].groupby("bookmaker")],
                })
        db.append(pd.DataFrame(proj_rows), "spread_projections")
        n = db.append(pd.DataFrame(card_rows), "cards") if card_rows else 0
        run.rows = n
        run.detail = {"games": len(proj_rows), "cards": n, "lean_plus": int(sum(r["lean_plus"] for r in proj_rows))}
        print(f"[score-spread] {season} wk{wk}: {len(proj_rows)} games, {n} picks, {run.detail['lean_plus']} lean+")
        return n


def _records(season: int, wk: int) -> dict[str, str]:
    g = db.read_sql("""SELECT home_team, away_team, home_score, away_score FROM raw_games
                       WHERE season=:s AND game_type='REG' AND week < :w AND home_score IS NOT NULL""", {"s": season, "w": wk})
    w, l, t = {}, {}, {}
    for r in g.itertuples():
        if r.home_score == r.away_score:
            t[r.home_team] = t.get(r.home_team, 0) + 1; t[r.away_team] = t.get(r.away_team, 0) + 1; continue
        win, lose = (r.home_team, r.away_team) if r.home_score > r.away_score else (r.away_team, r.home_team)
        w[win] = w.get(win, 0) + 1; l[lose] = l.get(lose, 0) + 1
    teams = set(w) | set(l) | set(t)
    return {x: f"{w.get(x, 0)}-{l.get(x, 0)}" + (f"-{t[x]}" if t.get(x) else "") for x in teams}


def _factors(g, m_used, mkt_margin, has_sharp, w, open_sp, cur_sp) -> list[dict]:
    H, A = TEAM_NAMES[g.home_team], TEAM_NAMES[g.away_team]
    F = []
    d = float(g.elo_diff)
    F.append({"factor": "elo", "value": round(d), "impact_home": 1 if d > 25 else -1 if d < -25 else 0, "magnitude": min(abs(d) / 150, 1),
              "text": f"Elo: {H} {g.elo_home:.0f} vs {A} {g.elo_away:.0f} (≈{d / 25:+.1f} pts before home field)",
              "source": {"table": "game_projections", "key": "elo_home"}})
    e = float(g.epa_diff) if pd.notna(g.epa_diff) else 0.0
    F.append({"factor": "epa_rating", "value": round(e, 3), "impact_home": 1 if e > 0.04 else -1 if e < -0.04 else 0, "magnitude": min(abs(e) / 0.15, 1) * 0.8,
              "text": f"EPA rating (off − def allowed): {H} {float(g.home_off_epa or 0) - float(g.home_def_epa or 0):+.3f} vs {A} {float(g.away_off_epa or 0) - float(g.away_def_epa or 0):+.3f} per play"
                      + (" — early season, small samples" if g.early_season else ""),
              "source": {"table": "feat_team_offense", "key": "epa_per_play"}})
    if pd.notna(g.rest_diff) and abs(g.rest_diff) >= 3:
        F.append({"factor": "rest", "value": float(g.rest_diff), "impact_home": 1 if g.rest_diff > 0 else -1, "magnitude": min(abs(g.rest_diff) / 7, 1) * 0.4,
                  "text": f"Rest: {H} {int(g.home_rest)} days vs {A} {int(g.away_rest)} days", "source": {"table": "raw_games", "key": "home_rest"}})
    for team, chg, starts, name, sign in ((g.home_team, g.home_qb_change, g.home_qb_starts, H, -1), (g.away_team, g.away_qb_change, g.away_qb_starts, A, 1)):
        if chg == 1:
            F.append({"factor": "qb_change", "value": team, "impact_home": sign, "magnitude": 0.5,
                      "text": f"{name} start a different QB than last game ({int(starts or 0)} prior NFL starts)", "source": {"table": "raw_depth_charts", "key": "QB1"}})
    if mkt_margin is not None:
        F.append({"factor": "model_vs_market", "value": round(float(g.m_raw), 1), "impact_home": 0, "magnitude": 0.3,
                  "text": f"Ratings model alone: {H} by {g.m_raw:+.1f}; market {mkt_margin:+.1f}" + (" (Pinnacle)" if has_sharp else " (book median)")
                          + f"; blended {int(w * 100)}% toward the market → {m_used:+.1f}. The raw model's MAE is worse than the closing line (MODEL.md).",
                  "source": {"table": "model_runs", "key": "metrics"}})
    if open_sp is not None and cur_sp is not None and open_sp != cur_sp:
        F.append({"factor": "line_move", "value": cur_sp - open_sp, "impact_home": 0, "magnitude": 0.2,
                  "text": f"Line moved {H} {open_sp:+.1f} → {cur_sp:+.1f} since the Tuesday open", "source": {"table": "odds_lines", "key": "line"}})
    return F
