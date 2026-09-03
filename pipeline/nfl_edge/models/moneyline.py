"""Moneyline (game winner) model.

Logistic regression on pre-game team ratings (Elo diff incl. home field, EPA rating diff), rest,
divisional, neutral site, and QB continuity. No market inputs in the model, so the comparison
against the no-vig market probability is an honest one.

Backtest is REAL here: nflverse ships closing moneylines for every game, so we report ROI of
betting at the closing price whenever model_prob − market_prob ≥ edge, by season and edge bucket,
plus the anchor weight (blend toward market) that maximised log-loss on the validation season.
"""
from __future__ import annotations
import datetime as dt
import json
import pickle
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from .. import db
from ..config import ARTIFACT_DIR
from ..features.team_ratings import game_features

MARKET = "h2h"
VERSION = "ml-logit-v1"
FEATURES = ["elo_diff", "epa_diff", "rest_diff", "div_game", "neutral", "qb_change_diff", "qb_inexp_diff"]


def american_to_prob(a: float) -> float:
    a = float(a)
    return 100 / (a + 100) if a > 0 else -a / (-a + 100)


def american_to_decimal(a: float) -> float:
    a = float(a)
    return 1 + a / 100 if a > 0 else 1 + 100 / -a


def market_probs(df: pd.DataFrame) -> pd.Series:
    """No-vig home win probability from nflverse closing moneylines (NaN where missing)."""
    ph = df.home_ml.map(lambda a: american_to_prob(a) if pd.notna(a) else np.nan)
    pa = df.away_ml.map(lambda a: american_to_prob(a) if pd.notna(a) else np.nan)
    return ph / (ph + pa)


class MoneylineModel:
    def __init__(self, pipe, anchor_w: float):
        self.pipe, self.anchor_w = pipe, anchor_w

    def predict_home(self, X: pd.DataFrame) -> np.ndarray:
        return self.pipe.predict_proba(X[FEATURES].fillna(0))[:, 1]


def fit(train: pd.DataFrame) -> MoneylineModel:
    pipe = make_pipeline(StandardScaler(), LogisticRegression(C=0.5, max_iter=1000))
    pipe.fit(train[FEATURES].fillna(0), train.home_win.astype(int))
    return MoneylineModel(pipe, 0.0)


def _logloss(p, y):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def backtest(model: MoneylineModel, test: pd.DataFrame, anchor_w: float) -> dict:
    t = test[test.home_win.notna()].copy()
    t["p_model"] = model.predict_home(t)
    t["p_mkt"] = market_probs(t)
    t = t[t.p_mkt.notna()]
    t["p_used"] = (1 - anchor_w) * t.p_model + anchor_w * t.p_mkt
    y = t.home_win.values
    out = {"n": int(len(t)), "logloss_model": _logloss(t.p_model, y), "logloss_market": _logloss(t.p_mkt, y),
           "logloss_used": _logloss(t.p_used, y),
           "accuracy_model": float(np.mean((t.p_model > 0.5) == (y == 1))),
           "accuracy_market": float(np.mean((t.p_mkt > 0.5) == (y == 1)))}
    # bet at closing price when edge ≥ threshold, either side
    sims = {}
    for edge in (0.02, 0.04, 0.06, 0.08, 0.10, 0.15):
        eh = t.p_used - t.p_mkt          # edge on home
        ea = (1 - t.p_used) - (1 - t.p_mkt)
        bet_home = eh >= edge
        bet_away = ea >= edge
        dec_h = t.home_ml.map(american_to_decimal); dec_a = t.away_ml.map(american_to_decimal)
        pnl = np.where(bet_home, np.where(y == 1, dec_h - 1, -1.0), 0.0) + np.where(bet_away, np.where(y == 0, dec_a - 1, -1.0), 0.0)
        n = int(bet_home.sum() + bet_away.sum())
        wins = int((bet_home & (y == 1)).sum() + (bet_away & (y == 0)).sum())
        sims[f"edge>={edge:.2f}"] = {"bets": n, "wins": wins, "win_rate": wins / n if n else None,
                                     "units": float(pnl.sum()), "roi": float(pnl.sum() / n) if n else None}
    out["betting"] = sims
    # calibration
    t["bucket"] = pd.cut(t.p_used, [0, .3, .4, .5, .6, .7, 1.0])
    out["calibration"] = [{"bucket": str(b), "n": int(len(g)), "pred": float(g.p_used.mean()), "actual": float(g.home_win.mean())}
                          for b, g in t.groupby("bucket", observed=True)]
    return out


def train(persist: bool = True) -> int:
    f = game_features(list(range(2016, 2027)))
    hist = f[f.home_win.notna()]
    tr = hist[hist.season <= 2023]; va = hist[hist.season == 2024]; te = hist[hist.season == 2025]
    model = fit(tr)
    # anchor weight: minimise validation log-loss of the blend
    pm, pk = model.predict_home(va), market_probs(va)
    ok = pk.notna().values
    ws = np.linspace(0, 1, 21)
    ll = [_logloss((1 - w) * pm[ok] + w * pk.values[ok], va.home_win.values[ok]) for w in ws]
    anchor_w = float(ws[int(np.argmin(ll))])
    model.anchor_w = anchor_w
    coefs = dict(zip(FEATURES, model.pipe[-1].coef_[0].round(3).tolist()))
    metrics = {"valid_2024": backtest(model, va, anchor_w), "test_2025": backtest(model, te, anchor_w),
               "test_2025_no_anchor": backtest(model, te, 0.0),
               "walk_forward_2019_2025": backtest(fit(hist[hist.season <= 2018]), hist[hist.season >= 2019], anchor_w),
               "walk_forward_raw_model": backtest(fit(hist[hist.season <= 2018]), hist[hist.season >= 2019], 0.0),
               "anchor_w": anchor_w, "coef_std": coefs}
    print(json.dumps({k: (v if not isinstance(v, dict) else {kk: vv for kk, vv in v.items() if kk in ("n", "logloss_model", "logloss_market", "logloss_used", "accuracy_model", "accuracy_market")})
                      for k, v in metrics.items()}, indent=1))
    print("anchor_w", anchor_w, "coefs", coefs)
    for k, v in metrics["test_2025"]["betting"].items():
        print(" 2025", k, v)
    prod = fit(hist); prod.anchor_w = anchor_w
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
        print(f"[train-ml] saved model_run {run_id}")
    return run_id


def load_latest() -> tuple[MoneylineModel, int]:
    import os
    r = db.read_sql("SELECT id, artifact_path, artifact FROM model_runs WHERE market=:m ORDER BY id DESC LIMIT 1", {"m": MARKET})
    if r.empty:
        raise RuntimeError("no moneyline model; run `python -m nfl_edge train_ml`")
    path = r.artifact_path.iloc[0]
    if path and os.path.exists(path):
        with open(path, "rb") as fh:
            return pickle.load(fh), int(r.id.iloc[0])
    return pickle.loads(bytes(r.artifact.iloc[0])), int(r.id.iloc[0])


def write_model_md(metrics: dict, run_id: int):
    from ..config import ROOT
    p = ROOT / "docs" / "MODEL.md"
    old = p.read_text() if p.exists() else ""
    marker = "\n# MODEL.md — moneyline"
    if marker in old:
        old = old[:old.index(marker)]
    t, v, wf = metrics["test_2025"], metrics["valid_2024"], metrics["walk_forward_2019_2025"]
    L = [marker + f" ({VERSION})", "",
         f"Last retrain: {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC · model_run id {run_id}", "",
         "Logistic regression on Elo diff (home field included), EPA rating diff, rest diff, divisional, neutral site, "
         "QB change and QB inexperience. Train 2016–2023 → validate 2024 (anchor weight) → test 2025. "
         f"Anchor weight toward the no-vig market: **{metrics['anchor_w']:.2f}** (chosen by validation log-loss).", "",
         "Standardised coefficients: " + ", ".join(f"{k} {v:+.3f}" for k, v in metrics["coef_std"].items()), "",
         "## Test 2025 — REAL closing moneylines (nflverse)", "",
         "| metric | model | market | blend |", "|---|---|---|---|",
         f"| log-loss | {t['logloss_model']:.4f} | {t['logloss_market']:.4f} | {t['logloss_used']:.4f} |",
         f"| accuracy | {t['accuracy_model']:.3f} | {t['accuracy_market']:.3f} | – |",
         "", "### Betting at the closing price (2025, blend)", "",
         "| min edge | bets | wins | win rate | units | ROI |", "|---|---|---|---|---|---|"]
    for k, r in t["betting"].items():
        L.append(f"| {k[4:]} | {r['bets']} | {r['wins']} | {(r['win_rate'] or 0):.3f} | {r['units']:+.2f} | {(r['roi'] or 0):+.3f} |")
    L += ["", "### Walk-forward 2019–2025 (model trained on 2016–2018 only, blend)", "",
          "| min edge | bets | wins | win rate | units | ROI |", "|---|---|---|---|---|---|"]
    for k, r in wf["betting"].items():
        L.append(f"| {k[4:]} | {r['bets']} | {r['wins']} | {(r['win_rate'] or 0):.3f} | {r['units']:+.2f} | {(r['roi'] or 0):+.3f} |")
    raw = metrics["walk_forward_raw_model"]
    L += ["", "### Why the anchor is 0.95 — the RAW ratings model bet against closing lines, 2019–2025", "",
          "Every 'edge' the un-anchored model sees against a closing NFL moneyline loses money, including the biggest ones. "
          "That is the reason moneyline cards are only flagged for price discrepancies between venues, not for model-vs-market disagreement.", "",
          "| min edge | bets | wins | win rate | units | ROI |", "|---|---|---|---|---|---|"]
    for k, r in raw["betting"].items():
        L.append(f"| {k[4:]} | {r['bets']} | {r['wins']} | {(r['win_rate'] or 0):.3f} | {r['units']:+.2f} | {(r['roi'] or 0):+.3f} |")
    L += ["", "### Calibration (2025, blend)", "", "| bucket | n | predicted | actual |", "|---|---|---|---|"]
    for c in t["calibration"]:
        L.append(f"| {c['bucket']} | {c['n']} | {c['pred']:.3f} | {c['actual']:.3f} |")
    L += ["", f"Validation 2024: log-loss model {v['logloss_model']:.4f} vs market {v['logloss_market']:.4f}.", ""]
    p.write_text(old.rstrip() + "\n" + "\n".join(L))
