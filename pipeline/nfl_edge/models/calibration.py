"""Learned edge calibration — the feedback loop for "confidence".

The projection models are calibrated on held-out seasons, but a *pick* is a comparison with a price, and
the market is not a random opponent: when the model disagrees with the book by a lot, the book is often the
one that is right. This module learns, from real graded bets, how much of a raw edge survives contact with
the market as a function of the situation:

    P(win) ~ logistic(edge, edge², |z|, market, side, sample size, new team, no opponent data,
                      new coaching staff, injury report seen, week, usage level)

Training rows come from two sources, stacked:
  1. the real closing-line backtests (`artifacts/backtest_<market>.parquet`, ~15k bets over 2023–25), and
  2. every graded live card (`grades` joined to `cards`), which is how the loop closes: each week's results
     re-fit the shrinkage, so a situation the model keeps getting wrong is trusted less next week.

Outputs, per candidate bet: `p_cal` (calibrated win probability) and `edge_cal = p_cal − fair`. Publishing
and Kelly use the calibrated edge; the raw edge is kept on the card for transparency.
"""
from __future__ import annotations
import datetime as dt
import glob
import json
import pickle
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from .. import db
from ..config import ARTIFACT_DIR, ROOT

MARKET_KEY = "calibration"
VERSION = "cal-logit-v1"
MARKETS = ["player_pass_yds", "player_reception_yds", "player_receptions", "player_rush_yds"]
USAGE_COL = {"player_pass_yds": "att_ewm", "player_reception_yds": "tgt_ewm", "player_receptions": "tgt_ewm", "player_rush_yds": "car_ewm"}
USAGE_SCALE = {"player_pass_yds": 35.0, "player_reception_yds": 8.0, "player_receptions": 8.0, "player_rush_yds": 15.0}
FEATURES = ["fair", "fair_logit", "edge", "edge_sq", "abs_z", "is_over", "games_career_lt8", "games_career_lt20", "new_team", "opp_no_data",
            "new_hc", "injury_seen", "week_early", "usage_norm", "sharp_agree", "sharp_disagree",
            "m_recy", "m_rec", "m_ruy"]


def _norm(s):
    import re
    s = re.sub(r"[^a-z ]", "", str(s).lower())
    s = re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", s)
    return " ".join(s.split())


def featurize(market: str, edge: float, mean_used: float, sd: float, line: float, side: str, X: dict,
              sharp_lean: int = 0, fair: float = 0.5) -> dict:
    """One row of calibration features from a card's context. sharp_lean: +1 agrees with side, −1 disagrees, 0 n/a.
    `fair` = the no-vig market probability of the side — essential: a +140 side with the same raw edge as a −110 side
    wins far less often, and Kelly needs P(win), not P(win) minus a constant."""
    g = lambda k, d=0.0: (X.get(k) if X.get(k) is not None else d)
    career = g("games_career")
    fair = min(max(float(fair), 0.02), 0.98)
    return {
        "fair": fair, "fair_logit": float(np.log(fair / (1 - fair))),
        "edge": edge, "edge_sq": edge * edge, "abs_z": abs(mean_used - line) / max(sd, 1e-6),
        "is_over": 1.0 if side == "Over" else 0.0,
        "games_career_lt8": 1.0 if career < 8 else 0.0, "games_career_lt20": 1.0 if career < 20 else 0.0,
        "new_team": float(g("new_team")), "opp_no_data": 1.0 if g("opp_games") == 0 else 0.0,
        "new_hc": float(g("new_hc")), "injury_seen": float(g("injury_report_seen", 1.0)),
        "week_early": 1.0 if g("week_num", 9) <= 3 else 0.0,
        "usage_norm": float(g(USAGE_COL[market])) / USAGE_SCALE[market],
        "sharp_agree": 1.0 if sharp_lean > 0 else 0.0, "sharp_disagree": 1.0 if sharp_lean < 0 else 0.0,
        "m_recy": 1.0 if market == "player_reception_yds" else 0.0, "m_rec": 1.0 if market == "player_receptions" else 0.0,
        "m_ruy": 1.0 if market == "player_rush_yds" else 0.0,
    }


def _backtest_rows() -> pd.DataFrame:
    """Backtest bets joined back to their feature rows (by game + normalised name)."""
    from .passing_yards import load_training as load_py
    from .player_props import load_training as load_pp, SPECS
    out = []
    for m in MARKETS:
        p = ARTIFACT_DIR / f"backtest_{m}.parquet"
        if not p.exists():   # stateless runner: rebuild the bet table from the committed closing-line fixtures
            try:
                from .backtest_lines import run as backtest_run
                backtest_run(grid=False, market=m)
            except Exception as e:
                print(f"[calibration] no backtest rows for {m}: {e}"); continue
        if not p.exists():
            continue
        b = pd.read_parquet(p)
        b = b[~b.push]
        df, _ = load_py() if m == "player_pass_yds" else load_pp(SPECS[m])
        df = df.copy(); df["nname"] = df.player_name.map(_norm)
        need = ["game_id", "nname", "games_career", "new_team", "opp_games", "new_hc", "injury_report_seen", "week_num", USAGE_COL[m]]
        j = b.merge(df[need].drop_duplicates(["game_id", "nname"]), on=["game_id", "nname"], how="inner")
        # the backtest stores sd implicitly via p; recover |z| from the empirical relation is not possible → use edge proxies
        for _, r in j.iterrows():
            X = {k: r[k] for k in need[2:]}
            f = featurize(m, float(r.edge), float(r.mean_used), 1.0, float(r.line), r.side, X, 0, float(r.fair))
            f["abs_z"] = abs(float(r.p) - 0.5) * 4   # monotone stand-in for |z| (p is the model's P(side))
            f["win"] = int(r.win); f["source"] = "backtest"; f["market"] = m
            out.append(f)
    return pd.DataFrame(out)


def _live_rows() -> pd.DataFrame:
    """Graded live cards (the feedback loop)."""
    r = db.read_sql("""SELECT c.market, c.side, c.edge, c.model_prob, c.market_prob, c.line, c.factors, gr.result,
                              f.features
                       FROM grades gr JOIN cards c ON c.id = gr.card_id
                       JOIN feat_player_game f ON f.season=c.season AND f.week=c.week AND f.player_id=c.player_id AND f.game_id=c.game_id
                       WHERE gr.result IN ('win','loss') AND c.market = ANY(:m)""", {"m": MARKETS})
    out = []
    for _, x in r.iterrows():
        X = json.loads(x.features) if isinstance(x.features, str) else x.features
        facs = x.factors if isinstance(x.factors, list) else json.loads(x.factors)
        sharp = next((f for f in facs if f.get("factor") == "sharp_line"), None)
        lean = 0
        if sharp:
            lean = int(sharp.get("impact_over", 0)) * (1 if x.side == "Over" else -1)
        f = featurize(x.market, float(x.edge), 0.0, 1.0, 0.0, x.side, X, lean, float(x.market_prob))
        f["abs_z"] = abs(float(x.model_prob) - 0.5) * 4
        f["win"] = 1 if x.result == "win" else 0; f["source"] = "live"; f["market"] = x.market
        out.append(f)
    return pd.DataFrame(out)


class Calibrator:
    def __init__(self, pipe, n_rows: int, n_live: int):
        self.pipe, self.n_rows, self.n_live = pipe, n_rows, n_live

    def p_win(self, rows: list[dict] | pd.DataFrame) -> np.ndarray:
        X = pd.DataFrame(rows)[FEATURES].fillna(0.0)
        return self.pipe.predict_proba(X)[:, 1]


def train(persist: bool = True) -> int | None:
    bt = _backtest_rows()
    live = _live_rows()
    data = pd.concat([bt, live], ignore_index=True) if len(live) else bt
    if data.empty:
        print("[calibration] no training rows (run backtest_lines first)"); return None
    # live results count more than backtest rows (they are the world we are actually betting into)
    w = np.where(data.source == "live", 3.0, 1.0)
    pipe = make_pipeline(StandardScaler(), LogisticRegression(C=0.3, max_iter=2000))
    pipe.fit(data[FEATURES].fillna(0.0), data.win, logisticregression__sample_weight=w)
    cal = Calibrator(pipe, int(len(data)), int(len(live)))
    # report: how much of the raw edge survives, by raw-edge bucket
    data["p_cal"] = cal.p_win(data)
    data["bucket"] = pd.cut(data.edge, [0, .04, .06, .08, .10, .15, 1.0])
    rep = data.groupby("bucket", observed=True).agg(n=("win", "size"), win_rate=("win", "mean"), p_cal=("p_cal", "mean"), raw_edge=("edge", "mean")).reset_index()
    rep["bucket"] = rep.bucket.astype(str)
    coefs = dict(zip(FEATURES, pipe[-1].coef_[0].round(3).tolist()))
    metrics = {"rows": int(len(data)), "live_rows": int(len(live)), "by_edge_bucket": rep.to_dict("records"), "coef_std": coefs,
               "win_rate_overall": float(data.win.mean())}
    print(f"[calibration] {len(data)} rows ({len(live)} live). Raw edge → realised win rate / calibrated p:")
    for r in rep.to_dict("records"):
        print(f"   edge {r['bucket']}: n={r['n']} win={r['win_rate']:.3f} p_cal={r['p_cal']:.3f}")
    if not persist:
        return None
    path = ARTIFACT_DIR / f"{MARKET_KEY}_{VERSION}.pkl"
    with open(path, "wb") as fh:
        pickle.dump(cal, fh)
    run_id = db.insert_returning_id("model_runs", {
        "market": MARKET_KEY, "version": VERSION, "train_seasons": [2023, 2024, 2025], "valid_seasons": [], "test_seasons": [],
        "metrics": metrics, "feature_names": FEATURES, "artifact_path": str(path)})
    from sqlalchemy import text
    with open(path, "rb") as fh, db.conn() as c:
        c.execute(text("UPDATE model_runs SET artifact=:b WHERE id=:id"), {"b": fh.read(), "id": run_id})
    print(f"[calibration] saved model_run {run_id}")
    return run_id


def load_latest() -> Calibrator | None:
    import os
    r = db.read_sql("SELECT id, artifact_path, artifact FROM model_runs WHERE market=:m ORDER BY id DESC LIMIT 1", {"m": MARKET_KEY})
    if r.empty:
        return None
    path = r.artifact_path.iloc[0]
    if path and os.path.exists(path):
        with open(path, "rb") as fh:
            return pickle.load(fh)
    return pickle.loads(bytes(r.artifact.iloc[0])) if r.artifact.iloc[0] is not None else None
