"""Generic player-prop projection models (Milestone 2): receiving yards, receptions, rushing yards.

Same machinery as passing_yards.py v2 — LightGBM mean + LightGBM |residual| scale, target modelled relative
to a league-environment column, empirical standardised residuals for the distribution, walk-forward
protocol (train ≤2022 → validate 2023 → test 2024–25; production refit on everything) — parameterised by a
MarketSpec so each market has its own artifact, feature filter and eligibility rule.

Receptions are integers: the line is x.5 so no pushes, and P(over) from a continuous distribution with the
+0.5 continuity shift is a good approximation at the counts involved (2–10).
"""
from __future__ import annotations
import dataclasses
import datetime as dt
import json
import pickle
import numpy as np
import pandas as pd
import lightgbm as lgb
from scipy.stats import norm
from .. import db
from ..config import ARTIFACT_DIR, ROOT
from .passing_yards import PARAMS, SCALE_PARAMS, _fit_mean, _oof_residuals, _calibrate_scale


@dataclasses.dataclass(frozen=True)
class MarketSpec:
    market: str            # Odds API market key
    version: str
    target: str            # feat_player_game column
    base_col: str          # league environment feature (target modelled relative to it)
    positions: tuple[str, ...]
    min_usage: str         # feature that must be ≥ min_usage_val for a training row / projection
    min_usage_val: float
    sd_floor: float
    label: str


SPECS: dict[str, MarketSpec] = {
    "player_reception_yds": MarketSpec("player_reception_yds", "recy-lgbm-v1", "target_receiving_yards", "league_recy_prev_season",
                                       ("WR", "TE", "RB", "FB"), "tgt_ewm", 2.0, 8.0, "Receiving Yards"),
    "player_receptions": MarketSpec("player_receptions", "rec-lgbm-v1", "target_receptions", "league_rec_prev_season",
                                    ("WR", "TE", "RB", "FB"), "tgt_ewm", 2.0, 0.8, "Receptions"),
    "player_rush_yds": MarketSpec("player_rush_yds", "ruy-lgbm-v1", "target_rushing_yards", "league_ruy_prev_season",
                                  ("RB", "FB", "WR"), "car_ewm", 4.0, 8.0, "Rushing Yards"),
}

# player-only feature subset for the proxy-market baseline (no opponent / context)
PLAYER_ONLY_PREFIXES = ("tgt_", "rec_", "recy_", "car_", "ruy_", "ypt_", "catch_rate", "adot", "ypc", "carry_share", "air_yards_share",
                        "wopr", "touches", "games_", "usage_trend", "carry_trend", "new_team", "days_since_last", "pos_", "week_num",
                        "receiving_air_yards_ewm", "tgt_share", "is_home")


class PropModel:
    def __init__(self, spec: MarketSpec, names, mean_model, scale_model, scale_cal, n_iter, z_emp):
        self.spec, self.names, self.mean_model, self.scale_model = spec, names, mean_model, scale_model
        self.scale_cal, self.n_iter, self.z_emp = scale_cal, n_iter, np.sort(z_emp)

    def _zq(self, p):
        return np.quantile(self.z_emp, p)

    def _zcdf(self, z):
        n = len(self.z_emp)
        return np.interp(z, self.z_emp, (np.arange(n) + 0.5) / n, left=0.0, right=1.0)

    def predict(self, X: pd.DataFrame) -> pd.DataFrame:
        base = X[self.spec.base_col].fillna(X[self.spec.base_col].mean()).values
        Xn = X[self.names]
        mean = self.mean_model.predict(Xn) + base
        sd = self.scale_cal * np.clip(self.scale_model.predict(Xn), self.spec.sd_floor, None) * np.sqrt(np.pi / 2)
        q = {f"q{p}": mean + self._zq(p / 100) * sd for p in (10, 25, 50, 75, 90)}
        return pd.DataFrame({"mean": mean, "sd": sd, **q})

    def p_over(self, mean, sd, line):
        return 1 - self._zcdf((np.asarray(line) + 0.5 - np.asarray(mean)) / np.asarray(sd))


def load_training(spec: MarketSpec) -> tuple[pd.DataFrame, list[str]]:
    r = db.read_sql(f"""SELECT season, week, game_id, player_id, player_name, position, team, opponent, features,
                               {spec.target} AS y
                        FROM feat_player_game WHERE {spec.target} IS NOT NULL AND position = ANY(:p)""",
                    {"p": list(spec.positions)})
    feats = pd.DataFrame([json.loads(f) if isinstance(f, str) else f for f in r.features])
    df = pd.concat([r.drop(columns=["features"]).reset_index(drop=True), feats], axis=1)
    df = df[df[spec.min_usage].fillna(0) >= spec.min_usage_val].reset_index(drop=True)
    names = [c for c in feats.columns if c not in ("as_of",)]
    return df, names


def fit(spec: MarketSpec, df: pd.DataFrame, names: list[str], train_seasons, valid_season) -> PropModel:
    df = df.copy()
    df["y"] = df.y - df[spec.base_col].fillna(df[spec.base_col].mean())
    tr, va = df[df.season.isin(train_seasons)], df[df.season == valid_season]
    m = _fit_mean(tr[names], tr.y, va[names], va.y)
    n_iter = m.best_iteration
    oof = _oof_residuals(tr[names].values, tr.y.values, tr.season.values, n_iter)
    sm = lgb.train(SCALE_PARAMS, lgb.Dataset(tr[names], np.abs(oof)), num_boost_round=max(100, n_iter // 2))
    k = _calibrate_scale(m.predict(va[names]), np.clip(sm.predict(va[names]), spec.sd_floor, None), va.y.values)
    z = oof / (k * np.clip(sm.predict(tr[names]), spec.sd_floor, None) * np.sqrt(np.pi / 2))
    return PropModel(spec, names, m, sm, k, n_iter, z)


def evaluate(model: PropModel, test: pd.DataFrame, proxy: PropModel | None = None) -> dict:
    pred = model.predict(test)
    y = test.y.values
    ewm_col = {"target_receiving_yards": "recy_ewm", "target_receptions": "rec_ewm", "target_rushing_yards": "ruy_ewm"}[model.spec.target]
    out = {"n": int(len(y)), "mae": float(np.mean(np.abs(y - pred["mean"]))),
           "rmse": float(np.sqrt(np.mean((y - pred["mean"]) ** 2))),
           "mae_baseline_ewm": float(np.nanmean(np.abs(y - test[ewm_col])))}
    for p in (10, 25, 75, 90):
        out[f"cov_q{p}"] = float(np.mean(y <= pred[f"q{p}"]))
    rows = []
    step = 1 if model.spec.target == "target_receptions" else 10
    for off in (-2 * step, -step, 0, step, 2 * step):
        line = np.round(pred["q50"] + off) + 0.5
        rows.append(pd.DataFrame({"p": model.p_over(pred["mean"], pred["sd"], line), "hit": (y > line).astype(int)}))
    cal = pd.concat(rows)
    cal["bucket"] = pd.cut(cal.p, [0, .2, .3, .4, .5, .6, .7, .8, 1.0])
    out["calibration"] = [{"bucket": str(b), "n": int(len(g)), "pred": float(g.p.mean()), "actual": float(g.hit.mean())}
                          for b, g in cal.groupby("bucket", observed=True)]
    if proxy is not None:
        pp = proxy.predict(test)
        line = np.round(pp["q50"]) + 0.5
        p_over = model.p_over(pred["mean"], pred["sd"], line)
        out["proxy"] = {"mae_proxy": float(np.mean(np.abs(y - pp["mean"])))}
        for edge in (0.02, 0.04, 0.06, 0.08):
            side = np.where(p_over >= 0.5 + edge, 1, np.where(p_over <= 0.5 - edge, -1, 0))
            hit = np.where(side == 1, y > line, np.where(side == -1, y < line, False))
            n = int((side != 0).sum()); wins = int(hit.sum())
            out["proxy"][f"edge>={edge:.2f}"] = {"bets": n, "wins": wins, "win_rate": (wins / n if n else None),
                                                "roi": ((wins * (100 / 110) - (n - wins)) / n if n else None)}
    return out


def train(market: str, persist: bool = True) -> int | None:
    spec = SPECS[market]
    df, names = load_training(spec)
    seasons = sorted(df.season.unique())
    last = int(seasons[-1])
    train_s, valid_s, test_s = [s for s in seasons if s <= 2022], 2023, [s for s in seasons if s >= 2024]
    print(f"[train:{market}] {len(df)} rows, {len(names)} features; train {train_s[0]}-{train_s[-1]}, valid {valid_s}, test {test_s}")
    model = fit(spec, df, names, train_s, valid_s)
    proxy_names = [n for n in names if n.startswith(PLAYER_ONLY_PREFIXES) or n == spec.base_col]
    proxy = fit(spec, df, proxy_names, train_s, valid_s)
    metrics = {"holdout": evaluate(model, df[df.season.isin(test_s)], proxy), "valid": evaluate(model, df[df.season == valid_s]),
               "n_iter": model.n_iter, "scale_cal": model.scale_cal, "rows": int(len(df))}
    imp = pd.Series(model.mean_model.feature_importance("gain"), index=names).sort_values(ascending=False)
    metrics["feature_importance"] = {k: float(v) for k, v in (imp / imp.sum()).head(25).items()}
    h = metrics["holdout"]
    print(f"[train:{market}] holdout MAE {h['mae']:.2f} (EWM baseline {h['mae_baseline_ewm']:.2f}, proxy {h['proxy']['mae_proxy']:.2f}) "
          f"cov q10/25/75/90 {h['cov_q10']:.3f}/{h['cov_q25']:.3f}/{h['cov_q75']:.3f}/{h['cov_q90']:.3f}")
    try:
        from .backtest_lines import run as backtest_real
        metrics["real_lines"] = backtest_real(market=market, grid=False)
    except Exception as e:
        print(f"[train:{market}] real-line backtest skipped: {e}")
    prod = fit(spec, df, names, [s for s in seasons if s < last], last)
    base = df[spec.base_col].fillna(df[spec.base_col].mean())
    prod.mean_model = _fit_mean(df[names], df.y - base, n_iter=prod.n_iter)
    metrics["prod"] = {"train_through": last, "n_iter": prod.n_iter, "scale_cal": prod.scale_cal}
    if not persist:
        return None
    path = ARTIFACT_DIR / f"{market}_{spec.version}.pkl"
    with open(path, "wb") as f:
        pickle.dump(prod, f)
    run_id = db.insert_returning_id("model_runs", {
        "market": market, "version": spec.version, "train_seasons": [int(s) for s in seasons], "valid_seasons": [valid_s],
        "test_seasons": [int(s) for s in test_s], "metrics": metrics, "feature_names": names, "artifact_path": str(path)})
    from sqlalchemy import text
    with open(path, "rb") as f, db.conn() as c:
        c.execute(text("UPDATE model_runs SET artifact=:b WHERE id=:id"), {"b": f.read(), "id": run_id})
    write_model_md(spec, metrics, names, run_id)
    print(f"[train:{market}] saved model_run {run_id}")
    return run_id


def load_latest(market: str) -> tuple[PropModel, int]:
    import os
    r = db.read_sql("SELECT id, artifact_path, artifact FROM model_runs WHERE market=:m ORDER BY id DESC LIMIT 1", {"m": market})
    if r.empty:
        raise RuntimeError(f"no trained model for {market}; run `python -m nfl_edge train_props`")
    path = r.artifact_path.iloc[0]
    if path and os.path.exists(path):
        with open(path, "rb") as f:
            return pickle.load(f), int(r.id.iloc[0])
    return pickle.loads(bytes(r.artifact.iloc[0])), int(r.id.iloc[0])


def write_model_md(spec: MarketSpec, metrics: dict, names: list[str], run_id: int):
    p = ROOT / "docs" / "MODEL.md"
    old = p.read_text() if p.exists() else ""
    marker = f"\n# MODEL.md — {spec.label.lower()}"
    if marker in old:
        nxt = old.find("\n# MODEL.md — ", old.index(marker) + 1)
        old = old[:old.index(marker)] + (old[nxt:] if nxt != -1 else "")
    h = metrics["holdout"]
    L = [marker + f" ({spec.version})", "", f"Last retrain: {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC · model_run id {run_id} · {metrics['rows']} training rows", "",
         f"Positions {', '.join(spec.positions)}; eligibility {spec.min_usage} ≥ {spec.min_usage_val}. Target modelled relative to `{spec.base_col}`; "
         f"empirical residual distribution; iterations {metrics['n_iter']}, scale k={metrics['scale_cal']:.3f}.", "",
         "## Holdout (2024–2025)", "", "| metric | value |", "|---|---|",
         f"| games | {h['n']} |", f"| MAE (model) | {h['mae']:.2f} |", f"| MAE baseline: EWM of player's stat | {h['mae_baseline_ewm']:.2f} |",
         f"| MAE proxy market (player-only) | {h['proxy']['mae_proxy']:.2f} |",
         f"| q10 / q25 / q75 / q90 coverage | {h['cov_q10']:.3f} / {h['cov_q25']:.3f} / {h['cov_q75']:.3f} / {h['cov_q90']:.3f} |",
         "", "### P(over) calibration at synthetic lines (holdout)", "", "| bucket | n | pred | actual |", "|---|---|---|---|"]
    L += [f"| {c['bucket']} | {c['n']} | {c['pred']:.3f} | {c['actual']:.3f} |" for c in h["calibration"]]
    if "real_lines" in metrics:
        rl = metrics["real_lines"]
        L += ["", f"### REAL closing lines {rl['seasons']} (1u flat at best price)", "", "| min edge | bets | W-L | win rate | units | ROI |", "|---|---|---|---|---|---|"]
        for k, r in rl["overall"].items():
            L.append(f"| {k[5:]} | {r['bets']} | {r['wins']}-{r['losses']} | {(r['win_rate'] or 0):.3f} | {r['units']:+.1f} | {(r['roi'] or 0):+.3f} |")
    L += ["", "## Top features (gain share)", "", "| feature | share |", "|---|---|"]
    L += [f"| {k} | {s:.3f} |" for k, s in metrics["feature_importance"].items()]
    p.write_text(old.rstrip() + "\n" + "\n".join(L) + "\n")
