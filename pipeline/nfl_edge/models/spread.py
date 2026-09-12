"""Game margin (spread) and total model — the NFL equivalent of a CFBD-contest margin model.

Two ridge regressions on pre-game team ratings (Elo diff incl. home field, EPA ratings, rest, divisional,
neutral, QB continuity): one for the home margin, one for the game total. Projected scores follow from the
pair: home = (total + margin) / 2. P(cover) comes from the empirical residual distribution of the margin model
(NFL margins are not normal — key numbers 3 and 7 — so we use the empirical CDF of walk-forward residuals).

Backtest is REAL: nflverse ships the closing spread (`spread_line`, home perspective) and total for every
game. We report, walk-forward by season, the model's MAE vs the market's, ATS record when the model and the
closing line disagree by ≥ k points, and — the honest headline — units at −110.

No market inputs in the model, so a disagreement is a genuine disagreement. The anchor weight (blend toward
the closing line) is chosen on the validation season by MAE, and the published projection uses it; the un-anchored
projection is stored too so the /games page can show both.
"""
from __future__ import annotations
import datetime as dt
import json
import pickle
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from .. import db
from ..config import ARTIFACT_DIR
from ..features.team_ratings import game_features

MARKET = "spreads"
VERSION = "spread-ridge-v1"
FEATURES = ["elo_diff", "epa_diff", "rest_diff", "div_game", "neutral", "qb_change_diff", "qb_inexp_diff", "early_season"]
TOTAL_FEATURES = ["off_sum", "def_sum", "elo_sum", "neutral", "early_season", "week_num"]
JUICE_BREAKEVEN = 110 / 210   # 52.38% at −110


def _prep(f: pd.DataFrame) -> pd.DataFrame:
    f = f.copy()
    # EPA ratings are noisy in the first weeks; let the model learn how much to trust them
    f["early_season"] = (f.week_num <= 4).astype(int)
    f["off_sum"] = f.home_off_epa.fillna(0) + f.away_off_epa.fillna(0)
    f["def_sum"] = f.home_def_epa.fillna(0) + f.away_def_epa.fillna(0)
    f["elo_sum"] = (f.elo_home.fillna(1500) + f.elo_away.fillna(1500)) / 2 - 1500
    f["margin"] = f.home_score - f.away_score
    f["total"] = f.home_score + f.away_score
    return f


class SpreadModel:
    def __init__(self, margin_pipe, total_pipe, resid: np.ndarray, anchor_w: float, total_anchor_w: float):
        self.margin_pipe, self.total_pipe = margin_pipe, total_pipe
        # least squares centres the MEAN residual; covering is about the MEDIAN (margins are skewed toward big
        # favourite blowouts), so the projection is shifted by the median walk-forward residual and the stored
        # residuals are re-centred on it → P(cover) of the projected side is ≥ 50% by construction
        self.bias = float(np.median(resid))
        self.resid = np.sort(np.asarray(resid) - self.bias)   # walk-forward margin residuals (actual − projected), un-anchored
        self.anchor_w, self.total_anchor_w = anchor_w, total_anchor_w

    def predict_margin(self, X: pd.DataFrame) -> np.ndarray:
        return self.margin_pipe.predict(X[FEATURES].fillna(0)) + getattr(self, "bias", 0.0)

    def predict_total(self, X: pd.DataFrame) -> np.ndarray:
        return self.total_pipe.predict(X[TOTAL_FEATURES].fillna(0))

    def p_home_cover(self, proj_margin: np.ndarray, spread: np.ndarray) -> np.ndarray:
        """P(actual margin > spread) under the empirical residual distribution centred on the projection.
        Pushes (margin == spread) count as half."""
        need = np.asarray(spread, float) - np.asarray(proj_margin, float)   # residual needed to cover
        gt = 1 - np.searchsorted(self.resid, need, side="right") / len(self.resid)
        eq = (np.searchsorted(self.resid, need, side="right") - np.searchsorted(self.resid, need, side="left")) / len(self.resid)
        return gt + 0.5 * eq

    @property
    def sd(self) -> float:
        return float(np.std(self.resid))


def fit(train: pd.DataFrame, resid: np.ndarray | None = None) -> SpreadModel:
    mp = make_pipeline(StandardScaler(), Ridge(alpha=3.0)).fit(train[FEATURES].fillna(0), train.margin)
    tp = make_pipeline(StandardScaler(), Ridge(alpha=3.0)).fit(train[TOTAL_FEATURES].fillna(0), train.total)
    if resid is None:
        resid = (train.margin - mp.predict(train[FEATURES].fillna(0))).values
    return SpreadModel(mp, tp, resid, 0.0, 0.0)


def walk_forward(hist: pd.DataFrame, first_test: int = 2019) -> pd.DataFrame:
    """Refit on all seasons < s and predict season s, for s ≥ first_test. Returns hist rows with proj_margin/proj_total."""
    out = []
    for s in sorted(hist.season.unique()):
        if s < first_test:
            continue
        m = fit(hist[hist.season < s])
        t = hist[hist.season == s].copy()
        t["proj_margin"] = m.predict_margin(t)
        t["proj_total"] = m.predict_total(t)
        out.append(t)
    return pd.concat(out)


def ats_table(t: pd.DataFrame, col: str = "proj_used") -> dict:
    """ATS record at −110 when |projection − closing spread| ≥ k, plus MAE comparison."""
    t = t[t.spread_line.notna() & t.margin.notna()].copy()
    res = {"n": int(len(t)), "mae_model": float((t.margin - t[col]).abs().mean()),
           "mae_market": float((t.margin - t.spread_line).abs().mean()),
           "mae_total_model": float((t.total - t.proj_total_used).abs().mean()) if "proj_total_used" in t else None,
           "mae_total_market": float((t.total - t.total_line).abs().mean()) if t.total_line.notna().any() else None,
           "su_model": float(np.mean(np.sign(t[col]) == np.sign(t.margin))),
           "su_market": float(np.mean(np.sign(t.spread_line) == np.sign(t.margin)))}
    gap = t[col] - t.spread_line                 # >0: model likes home more than the market → bet home
    covered_home = np.sign(t.margin - t.spread_line)   # +1 home covers, −1 away covers, 0 push
    sims = {}
    for k in (0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 7.0):
        bet = gap.abs() >= k if k > 0 else gap.abs() > 0
        side = np.sign(gap)
        r = covered_home[bet] * side[bet]
        w, l, p = int((r > 0).sum()), int((r < 0).sum()), int((r == 0).sum())
        units = w * (100 / 110) - l
        sims[f"gap>={k:.0f}"] = {"bets": int(bet.sum()), "w": w, "l": l, "p": p,
                                 "win_rate": w / (w + l) if w + l else None, "units": float(units),
                                 "roi": float(units / bet.sum()) if bet.sum() else None}
    res["ats"] = sims
    return res


def train(persist: bool = True) -> int | None:
    f = _prep(game_features(list(range(2016, 2027))))
    hist = f[f.margin.notna() & f.spread_line.notna()]
    wf = walk_forward(hist, 2019)
    # anchor weight toward the closing line: minimise 2024 MAE (validation), report 2025 (test) and 2019–2025
    va = wf[wf.season == 2024]
    ws = np.linspace(0, 1, 21)
    mae = [float((va.margin - ((1 - w) * va.proj_margin + w * va.spread_line)).abs().mean()) for w in ws]
    anchor_w = float(ws[int(np.argmin(mae))])
    vt = va[va.total_line.notna()]
    maet = [float((vt.total - ((1 - w) * vt.proj_total + w * vt.total_line)).abs().mean()) for w in ws]
    total_anchor_w = float(ws[int(np.argmin(maet))])
    wf["proj_used"] = (1 - anchor_w) * wf.proj_margin + anchor_w * wf.spread_line
    wf["proj_total_used"] = np.where(wf.total_line.notna(), (1 - total_anchor_w) * wf.proj_total + total_anchor_w * wf.total_line.fillna(0), wf.proj_total)
    wf["proj_raw"] = wf.proj_margin
    resid = (wf.margin - wf.proj_margin).values
    metrics = {
        "anchor_w": anchor_w, "total_anchor_w": total_anchor_w, "resid_sd": float(np.std(resid)),
        "test_2025_raw": ats_table(wf[wf.season == 2025], "proj_raw"),
        "test_2025_blend": ats_table(wf[wf.season == 2025], "proj_used"),
        "walk_forward_2019_2025_raw": ats_table(wf, "proj_raw"),
        "walk_forward_2019_2025_blend": ats_table(wf, "proj_used"),
        "by_season_raw": {int(s): {"mae_model": r["mae_model"], "mae_market": r["mae_market"], "ats_gap3": r["ats"]["gap>=3"]}
                          for s, r in ((s, ats_table(g, "proj_raw")) for s, g in wf.groupby("season"))},
        "weeks_1_4_raw": ats_table(wf[wf.week_num <= 4], "proj_raw"),
        "weeks_5_plus_raw": ats_table(wf[wf.week_num > 4], "proj_raw"),
    }
    prod = fit(hist, resid); prod.anchor_w, prod.total_anchor_w = anchor_w, total_anchor_w
    coefs = dict(zip(FEATURES, prod.margin_pipe[-1].coef_.round(3).tolist()))
    metrics["coef_std"] = coefs
    print(json.dumps({k: v for k, v in metrics.items() if k in ("anchor_w", "total_anchor_w", "resid_sd", "coef_std")}))
    for k in ("walk_forward_2019_2025_raw", "test_2025_raw", "weeks_1_4_raw", "weeks_5_plus_raw"):
        r = metrics[k]
        print(f" {k}: n={r['n']} MAE model {r['mae_model']:.2f} vs market {r['mae_market']:.2f}; SU {r['su_model']:.3f} vs {r['su_market']:.3f}")
        for kk, vv in r["ats"].items():
            print(f"   {kk}: {vv['w']}-{vv['l']}-{vv['p']} ({(vv['win_rate'] or 0):.3f}) {vv['units']:+.1f}u ROI {(vv['roi'] or 0):+.3f}")
    run_id = None
    if persist:
        path = ARTIFACT_DIR / f"{MARKET}_{VERSION}.pkl"
        with open(path, "wb") as fh:
            pickle.dump(prod, fh)
        run_id = db.insert_returning_id("model_runs", {
            "market": MARKET, "version": VERSION, "train_seasons": sorted(int(s) for s in hist.season.unique()),
            "valid_seasons": [2024], "test_seasons": [2025], "metrics": metrics, "feature_names": FEATURES,
            "artifact_path": str(path)})
        from sqlalchemy import text
        with open(path, "rb") as fh, db.conn() as c:
            c.execute(text("UPDATE model_runs SET artifact=:b WHERE id=:id"), {"b": fh.read(), "id": run_id})
        write_model_md(metrics, run_id)
        print(f"[train-spread] saved model_run {run_id}")
    return run_id


def load_latest() -> tuple[SpreadModel, int]:
    import os
    r = db.read_sql("SELECT id, artifact_path, artifact FROM model_runs WHERE market=:m ORDER BY id DESC LIMIT 1", {"m": MARKET})
    if r.empty:
        raise RuntimeError("no spread model; run `python -m nfl_edge train_spread`")
    path = r.artifact_path.iloc[0]
    if path and os.path.exists(path):
        with open(path, "rb") as fh:
            return pickle.load(fh), int(r.id.iloc[0])
    return pickle.loads(bytes(r.artifact.iloc[0])), int(r.id.iloc[0])


def _ats_rows(r: dict) -> list[str]:
    L = ["| min gap | bets | W-L-P | win rate | units (−110) | ROI |", "|---|---|---|---|---|---|"]
    for k, v in r["ats"].items():
        L.append(f"| {k[5:]} pts | {v['bets']} | {v['w']}-{v['l']}-{v['p']} | {(v['win_rate'] or 0):.3f} | {v['units']:+.1f} | {(v['roi'] or 0):+.3f} |")
    return L


def write_model_md(metrics: dict, run_id: int):
    from ..config import ROOT
    p = ROOT / "docs" / "MODEL.md"
    old = p.read_text() if p.exists() else ""
    marker = "\n# MODEL.md — spreads & totals"
    if marker in old:
        old = old[:old.index(marker)]
    wf, t, e, l = metrics["walk_forward_2019_2025_raw"], metrics["test_2025_raw"], metrics["weeks_1_4_raw"], metrics["weeks_5_plus_raw"]
    L = [marker + f" ({VERSION})", "",
         f"Last retrain: {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC · model_run id {run_id}", "",
         "Ridge regression for the home margin on Elo diff (home field included), EPA rating diff, rest diff, divisional, "
         "neutral site, QB change, QB inexperience and an early-season flag; a second ridge for the game total. "
         "Walk-forward: every season 2019–2025 is predicted by a model fit on the seasons before it. "
         f"Residual sd {metrics['resid_sd']:.2f} pts. Anchor weight toward the closing spread chosen on 2024 by MAE: "
         f"**{metrics['anchor_w']:.2f}** (total: {metrics['total_anchor_w']:.2f}).", "",
         "Standardised coefficients: " + ", ".join(f"{k} {v:+.3f}" for k, v in metrics["coef_std"].items()), "",
         "## Walk-forward 2019–2025 — RAW model vs the closing spread (nflverse)", "",
         f"MAE model **{wf['mae_model']:.2f}** vs market **{wf['mae_market']:.2f}** · straight-up {wf['su_model']:.3f} vs {wf['su_market']:.3f} · n={wf['n']}", "",
         *_ats_rows(wf), "",
         "## Test 2025 — RAW model", "",
         f"MAE model {t['mae_model']:.2f} vs market {t['mae_market']:.2f} · n={t['n']}", "", *_ats_rows(t), "",
         "## Weeks 1–4 vs weeks 5+ (walk-forward, RAW) — where a ratings model can and cannot beat the line", "",
         f"Weeks 1–4: MAE {e['mae_model']:.2f} vs {e['mae_market']:.2f}", "", *_ats_rows(e), "",
         f"Weeks 5+: MAE {l['mae_model']:.2f} vs {l['mae_market']:.2f}", "", *_ats_rows(l), "",
         "## By season (RAW, gap ≥ 3)", "", "| season | MAE model | MAE market | bets | W-L-P | units |", "|---|---|---|---|---|---|"]
    for s, r in metrics["by_season_raw"].items():
        a = r["ats_gap3"]
        L.append(f"| {s} | {r['mae_model']:.2f} | {r['mae_market']:.2f} | {a['bets']} | {a['w']}-{a['l']}-{a['p']} | {a['units']:+.1f} |")
    L += ["", "The /games page shows the blended projection (what we would actually bet off) and the raw one. Spread picks are "
          "flagged as bets only where the table above shows the gap bucket is profitable out of sample; otherwise the pick "
          "is shown as a lean with no stake, exactly like the moneyline layer.", ""]
    p.write_text(old.rstrip() + "\n" + "\n".join(L))
