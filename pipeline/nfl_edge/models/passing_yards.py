"""Passing-yards projection model.

Two LightGBM regressors:
  mean_model  : E[passing_yards | features]            (L2 objective)
  scale_model : E[|residual| | features]               (L2 on |resid| of out-of-fold mean predictions)
Distribution : v2 — EMPIRICAL. Standardised out-of-fold residuals z = (y − mean) / sd from the training
               seasons form the residual distribution (sd = SCALE_CAL * E|resid| * sqrt(pi/2), SCALE_CAL
               fitted on the validation season for 25/75 coverage). Passing-yard residuals are left-skewed
               (benchings, blowouts, in-game injuries) so a Normal over-prices the under side; the
               empirical z-distribution keeps the skew.
P(over line) = 1 - F_z((line + 0.5 - mean) / sd)   (+0.5 continuity; lines are x.5 so no pushes)

Walk-forward protocol (docs/MODEL.md): train 2016-2022, validate 2023, test 2024-2025 for the
reported metrics; the production artifact is then refit on all seasons through the last completed one.

Historical closing prop lines are not available from a free source, so the "market" baseline in the
backtest is a PROXY: a LightGBM fit on player-only rolling features (no opponent / context). This is
what "the book already knows the average" looks like, and it is labelled as a proxy everywhere.
"""
from __future__ import annotations
import json
import pickle
import datetime as dt
import numpy as np
import pandas as pd
import lightgbm as lgb
from scipy.stats import norm
from .. import db
from ..config import ARTIFACT_DIR

MARKET = "player_pass_yds"
VERSION = "py-lgbm-v2"
PLAYER_ONLY = ["py_l3", "py_l5", "py_l10", "py_sd_l10", "py_ewm", "att_l3", "att_l5", "att_ewm", "ypa_l10",
               "ypa_ewm", "epa_att_ewm", "cpoe_ewm", "air_yds_ewm", "rush_yds_ewm", "sack_rate_ewm",
               "py_std_avg", "games_std", "py_prev_season", "games_prev_season", "games_career", "usage_trend",
               "new_team", "days_since_last", "is_home", "week_num"]
# v2: the target is modelled RELATIVE to the league passing environment (previous season's mean starter
# passing yards). Trees cannot extrapolate, and league passing fell from 246 (2016) to 216 (2025) yds/game;
# training on the raw target left a −6 to −9 yard over-projection on 2024–25 holdouts. The offset column
# is a feature too, so the model still sees the level.
BASE_COL = "league_py_prev_season"
PARAMS = dict(objective="regression", learning_rate=0.02, num_leaves=7, min_data_in_leaf=60,
              feature_fraction=0.7, bagging_fraction=0.8, bagging_freq=1, lambda_l2=5.0, verbose=-1, seed=7)
SCALE_PARAMS = dict(PARAMS, num_leaves=7, min_data_in_leaf=80)


def load_training() -> tuple[pd.DataFrame, list[str]]:
    r = db.read_sql("""SELECT season, week, game_id, player_id, player_name, team, opponent, features,
                              target_passing_yards AS y, target_attempts AS att
                       FROM feat_player_game WHERE target_passing_yards IS NOT NULL""")
    feats = pd.DataFrame([json.loads(f) if isinstance(f, str) else f for f in r.features])
    names = list(feats.columns)
    return pd.concat([r.drop(columns=["features"]).reset_index(drop=True), feats], axis=1), names


def _fit_mean(X, y, Xv=None, yv=None, n_iter=None):
    d = lgb.Dataset(X, y)
    if n_iter:
        return lgb.train(PARAMS, d, num_boost_round=n_iter)
    return lgb.train(PARAMS, d, num_boost_round=3000, valid_sets=[lgb.Dataset(Xv, yv)],
                     callbacks=[lgb.early_stopping(100, verbose=False)])


def _oof_residuals(X, y, seasons, n_iter):
    """Out-of-fold signed residuals by season so the scale model isn't trained on overfit residuals."""
    res = np.zeros(len(y))
    for s in np.unique(seasons):
        tr = seasons != s
        m = _fit_mean(X[tr], y[tr], n_iter=n_iter)
        res[~tr] = y[~tr] - m.predict(X[~tr])
    return res


def _calibrate_scale(mean, raw_scale, y):
    """Find k so that Normal(mean, k*raw*sqrt(pi/2)) has correct 25/75 coverage on validation."""
    best, best_err = 1.0, 1e9
    for k in np.linspace(0.7, 1.5, 33):
        sd = k * raw_scale * np.sqrt(np.pi / 2)
        z = (y - mean) / sd
        cov = np.mean(np.abs(z) < norm.ppf(0.75))
        err = abs(cov - 0.5)
        if err < best_err:
            best, best_err = k, err
    return float(best)


class PassingYardsModel:
    def __init__(self, names, mean_model, scale_model, scale_cal, n_iter, z_emp=None):
        self.names, self.mean_model, self.scale_model, self.scale_cal, self.n_iter = names, mean_model, scale_model, scale_cal, n_iter
        self.z_emp = np.sort(z_emp) if z_emp is not None else None   # standardised OOF residuals (v2)

    def _zq(self, p):
        return norm.ppf(p) if self.z_emp is None else np.quantile(self.z_emp, p)

    def _zcdf(self, z):
        if self.z_emp is None:
            return norm.cdf(z)
        # smoothed ECDF: linear interpolation between order statistics
        n = len(self.z_emp)
        return np.interp(z, self.z_emp, (np.arange(n) + 0.5) / n, left=0.0, right=1.0)

    def predict(self, X: pd.DataFrame) -> pd.DataFrame:
        base = X[BASE_COL].fillna(X[BASE_COL].mean()).values if (BASE_COL in X and getattr(self, "relative", False)) else 0.0
        X = X[self.names]
        mean = self.mean_model.predict(X) + base
        sd = self.scale_cal * np.clip(self.scale_model.predict(X), 20, None) * np.sqrt(np.pi / 2)
        q = {f"q{p}": mean + self._zq(p / 100) * sd for p in (10, 25, 50, 75, 90)}
        return pd.DataFrame({"mean": mean, "sd": sd, **q})

    def p_over(self, mean, sd, line):
        return 1 - self._zcdf((np.asarray(line) + 0.5 - np.asarray(mean)) / np.asarray(sd))


def fit(df: pd.DataFrame, names: list[str], train_seasons, valid_season) -> PassingYardsModel:
    df = df.copy()
    df["y"] = df.y - df[BASE_COL].fillna(df[BASE_COL].mean())   # relative target (see BASE_COL)
    tr, va = df[df.season.isin(train_seasons)], df[df.season == valid_season]
    m = _fit_mean(tr[names], tr.y, va[names], va.y)
    n_iter = m.best_iteration
    oof = _oof_residuals(tr[names].values, tr.y.values, tr.season.values, n_iter)
    sm = lgb.train(SCALE_PARAMS, lgb.Dataset(tr[names], np.abs(oof)), num_boost_round=max(100, n_iter // 2))
    k = _calibrate_scale(m.predict(va[names]), np.clip(sm.predict(va[names]), 20, None), va.y.values)
    # empirical residual shape from the training OOF residuals, standardised by the (calibrated) scale
    z = oof / (k * np.clip(sm.predict(tr[names]), 20, None) * np.sqrt(np.pi / 2))
    model = PassingYardsModel(names, m, sm, k, n_iter, z_emp=z)
    model.relative = True
    return model


def evaluate(model: PassingYardsModel, test: pd.DataFrame, proxy: PassingYardsModel | None = None) -> dict:
    pred = model.predict(test)
    y = test.y.values
    out = {"n": int(len(y)), "mae": float(np.mean(np.abs(y - pred["mean"]))),
           "rmse": float(np.sqrt(np.mean((y - pred["mean"]) ** 2))),
           "mae_baseline_ewm": float(np.nanmean(np.abs(y - test.py_ewm))),
           "mae_baseline_prev_season": float(np.nanmean(np.abs(y - test.py_prev_season)))}
    # quantile coverage
    for p in (10, 25, 75, 90):
        out[f"cov_q{p}"] = float(np.mean(y <= pred[f"q{p}"]))
    # P(over) calibration at synthetic lines around the median
    rows = []
    for off in (-40, -20, -10, 0, 10, 20, 40):
        line = np.round(pred["q50"] + off) + 0.5
        p = model.p_over(pred["mean"], pred["sd"], line)
        rows.append(pd.DataFrame({"p": p, "hit": (y > line).astype(int)}))
    cal = pd.concat(rows)
    cal["bucket"] = pd.cut(cal.p, [0, .2, .3, .4, .5, .6, .7, .8, 1.0])
    out["calibration"] = [{"bucket": str(b), "n": int(len(g)), "pred": float(g.p.mean()), "actual": float(g.hit.mean())}
                          for b, g in cal.groupby("bucket", observed=True)]
    if proxy is not None:
        # PROXY market: line = proxy median; bet sides where |model_p - 0.5| >= edge at -110
        pp = proxy.predict(test)
        line = np.round(pp["q50"]) + 0.5
        p_over = model.p_over(pred["mean"], pred["sd"], line)
        out["proxy"] = {"mae_proxy": float(np.mean(np.abs(y - pp["mean"])))}
        for edge in (0.02, 0.04, 0.06, 0.08):
            side = np.where(p_over >= 0.5 + edge, 1, np.where(p_over <= 0.5 - edge, -1, 0))
            hit = np.where(side == 1, y > line, np.where(side == -1, y < line, False))
            n = int((side != 0).sum())
            wins = int(hit.sum())
            units = wins * (100 / 110) - (n - wins)
            out["proxy"][f"edge>={edge:.2f}"] = {"bets": n, "wins": wins, "win_rate": (wins / n if n else None),
                                                "roi": (units / n if n else None)}
    return out


def train(persist: bool = True) -> int:
    df, names = load_training()
    seasons = sorted(df.season.unique())
    last = int(seasons[-1])
    train_s, valid_s, test_s = [s for s in seasons if s <= 2022], 2023, [s for s in seasons if s >= 2024]
    print(f"[train] {len(df)} rows, {len(names)} features; train {train_s[0]}-{train_s[-1]}, valid {valid_s}, test {test_s}")

    model = fit(df, names, train_s, valid_s)
    proxy = fit(df, [n for n in PLAYER_ONLY if n in names], train_s, valid_s)
    metrics = {"holdout": evaluate(model, df[df.season.isin(test_s)], proxy),
               "valid": evaluate(model, df[df.season == valid_s]),
               "n_iter": model.n_iter, "scale_cal": model.scale_cal}
    imp = pd.Series(model.mean_model.feature_importance("gain"), index=names).sort_values(ascending=False)
    metrics["feature_importance"] = {k: float(v) for k, v in (imp / imp.sum()).head(25).items()}
    print(json.dumps({k: v for k, v in metrics["holdout"].items() if k != "calibration"}, indent=1))

    # production refit: train through last-1, validate on last season for early stopping + scale cal
    prod = fit(df, names, [s for s in seasons if s < last], last)
    # then refit the mean model on everything with the chosen iteration count
    prod.mean_model = _fit_mean(df[names], df.y - df[BASE_COL].fillna(df[BASE_COL].mean()), n_iter=prod.n_iter)
    metrics["prod"] = {"train_through": last, "n_iter": prod.n_iter, "scale_cal": prod.scale_cal}

    run_id = None
    if persist:
        path = ARTIFACT_DIR / f"{MARKET}_{VERSION}.pkl"
        with open(path, "wb") as f:
            pickle.dump(prod, f)
        run_id = db.insert_returning_id("model_runs", {
            "market": MARKET, "version": VERSION, "train_seasons": [int(s) for s in seasons],
            "valid_seasons": [valid_s], "test_seasons": [int(s) for s in test_s],
            "metrics": metrics, "feature_names": names, "artifact_path": str(path)})
        with open(path, "rb") as f, db.conn() as c:
            from sqlalchemy import text
            c.execute(text("UPDATE model_runs SET artifact=:b WHERE id=:id"), {"b": f.read(), "id": run_id})
        write_model_md(metrics, names, run_id)
        print(f"[train] saved model_run {run_id} → {path}")
    return run_id


def load_latest() -> tuple[PassingYardsModel, int]:
    r = db.read_sql("SELECT id, artifact_path, artifact FROM model_runs WHERE market=:m ORDER BY id DESC LIMIT 1", {"m": MARKET})
    if r.empty:
        raise RuntimeError("no trained model; run `python -m nfl_edge train`")
    import os
    path = r.artifact_path.iloc[0]
    if path and os.path.exists(path):
        with open(path, "rb") as f:
            return pickle.load(f), int(r.id.iloc[0])
    blob = r.artifact.iloc[0]
    if blob is None:
        raise RuntimeError("model artifact missing on disk and in DB; run `python -m nfl_edge train`")
    return pickle.loads(bytes(blob)), int(r.id.iloc[0])


def write_model_md(metrics: dict, names: list[str], run_id: int):
    from ..config import ROOT
    h, v = metrics["holdout"], metrics["valid"]
    lines = [f"# MODEL.md — passing yards ({VERSION})", "",
             f"Last retrain: {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC · model_run id {run_id}", "",
             "## Protocol", "",
             "Walk-forward: train 2016–2022 → validate 2023 (early stopping, scale calibration) → test 2024–2025. "
             "Production artifact refit on all seasons with the validated iteration count. Target = passing yards "
             "in games with ≥10 attempts, modelled RELATIVE to the previous season's league-average starter passing "
             "yards (v2; removes the era-drift bias that over-projected 2024–25 by 6–9 yds). "
             "Distribution = mean + heteroscedastic sd × empirical standardised-residual distribution (v2; replaces the Normal). "
             f"Mean model iterations {metrics['n_iter']}, scale calibration k={metrics['scale_cal']:.3f}.", "",
             "v2 feature additions: coaching-regime flag (new head coach → league-average tendency priors), script-neutral "
             "pass rate / pace / shotgun / no-huddle rates, injury context (own skill & OL outs, share of prior targets ruled out, "
             "WR1 out; opponent DB and front-seven outs) from 2016–2025 official reports + live ESPN feed, and league passing "
             "environment (rolling 8-week and prior-season means).", "",
             "## Holdout (2024–2025)", "",
             "| metric | value |", "|---|---|",
             f"| games | {h['n']} |", f"| MAE (model) | {h['mae']:.2f} |", f"| RMSE | {h['rmse']:.2f} |",
             f"| MAE baseline: EWM of player's yards | {h['mae_baseline_ewm']:.2f} |",
             f"| MAE baseline: previous-season avg | {h['mae_baseline_prev_season']:.2f} |",
             f"| MAE proxy market (player-only LGBM) | {h['proxy']['mae_proxy']:.2f} |",
             f"| q10 / q25 / q75 / q90 coverage | {h['cov_q10']:.3f} / {h['cov_q25']:.3f} / {h['cov_q75']:.3f} / {h['cov_q90']:.3f} (ideal .10/.25/.75/.90) |",
             "", "### P(over) calibration at synthetic lines (holdout)", "",
             "| predicted bucket | n | mean predicted | actual over rate |", "|---|---|---|---|"]
    for c in h["calibration"]:
        lines.append(f"| {c['bucket']} | {c['n']} | {c['pred']:.3f} | {c['actual']:.3f} |")
    lines += ["", "### Simulated betting vs PROXY market (holdout) — NOT real closing lines", "",
              "Lines = proxy model median (player-only features, no opponent/context) ± 0.5; price −110 both sides. "
              "This measures whether matchup/context features add information over a 'the book knows the average' "
              "line. Real closing-line ROI accrues in the track record from live snapshots only.", "",
              "| min edge | bets | wins | win rate | ROI |", "|---|---|---|---|---|"]
    for k, r in h["proxy"].items():
        if k.startswith("edge"):
            wr = f"{r['win_rate']:.3f}" if r["win_rate"] is not None else "–"
            roi = f"{r['roi']:+.3f}" if r["roi"] is not None else "–"
            lines.append(f"| {k[5:]} | {r['bets']} | {r['wins']} | {wr} | {roi} |")
    lines += ["", "## Validation (2023)", "", f"MAE {v['mae']:.2f} · coverage q25 {v['cov_q25']:.3f} / q75 {v['cov_q75']:.3f}", "",
              "## Top features (gain share)", "", "| feature | share |", "|---|---|"]
    for k, s in metrics["feature_importance"].items():
        lines.append(f"| {k} | {s:.3f} |")
    lines += ["", f"All {len(names)} features: " + ", ".join(names), ""]
    (ROOT / "docs" / "MODEL.md").write_text("\n".join(lines))
