"""Backtest the passing-yards model against REAL historical closing lines (The Odds API historical
endpoints, fetched by `odds_history`, stored in pipeline/fixtures/odds_history/<season>.parquet).

Protocol (mirrors production exactly):
  * for test season S: fit on seasons < S−1 with S−1 as the validation season (early stopping +
    scale calibration + empirical residuals), then refit the mean model on all seasons < S;
  * score every (QB, week) with a closing line: level anchor (median line−model gap across the
    week's QBs × LEVEL_W) then per-player anchor (ANCHOR_W toward the consensus line), P(over)
    from the model distribution, EV per book/line, best side per QB — same code path as cards.py;
  * bet 1u flat on every side whose edge ≥ threshold, settle at the actual passing yards and the
    price taken. Report bets / wins / ROI by edge bucket, by side, by season, and the anchor-weight
    grid so the weights are chosen from money, not from hunches.
"""
from __future__ import annotations
import datetime as dt
import json
import re
import numpy as np
import pandas as pd
from ..config import ROOT, LEVEL_ANCHOR_W, MARKET_ANCHOR_W
from ..ingest.odds_history import load_fixtures
from . import passing_yards as PY


def _norm(s: str) -> str:
    s = re.sub(r"[^a-z ]", "", str(s).lower())
    s = re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", s)
    return " ".join(s.split())


def main_lines(lines: pd.DataFrame, market: str = "player_pass_yds") -> pd.DataFrame:
    """One two-way price per (game, player, book): the book's main line = the alternate closest to even money."""
    l = lines[lines.market == market].copy()
    l["nname"] = l.player.map(_norm)
    o = l[l.side == "Over"][["season", "week", "game_id", "nname", "bookmaker", "line", "price_decimal"]].rename(columns={"price_decimal": "over_dec"})
    u = l[l.side == "Under"][["game_id", "nname", "bookmaker", "line", "price_decimal"]].rename(columns={"price_decimal": "under_dec"})
    two = o.merge(u, on=["game_id", "nname", "bookmaker", "line"])
    two["skew"] = (two.over_dec - two.under_dec).abs()
    two = two.sort_values("skew").drop_duplicates(["game_id", "nname", "bookmaker"])
    po, pu = 1 / two.over_dec, 1 / two.under_dec
    two["over_fair"], two["under_fair"] = po / (po + pu), pu / (po + pu)
    return two.drop(columns="skew")


class _Adapter:
    """Market-specific fit/refit so the backtest is one code path for every prop model."""
    def __init__(self, market: str):
        self.market = market
        if market == "player_pass_yds":
            self.spec = None
        else:
            from .player_props import SPECS
            self.spec = SPECS[market]

    def load(self):
        if self.spec is None:
            return PY.load_training()
        from .player_props import load_training
        return load_training(self.spec)

    def fit(self, df, names, tr, va):
        if self.spec is None:
            return PY.fit(df, names, tr, va)
        from .player_props import fit
        return fit(self.spec, df, names, tr, va)

    @property
    def base_col(self):
        return PY.BASE_COL if self.spec is None else self.spec.base_col


def score_season(df: pd.DataFrame, names: list[str], lines: pd.DataFrame, season: int,
                 level_w: float, anchor_w: float, model=None, adapter: _Adapter | None = None):
    """Return (bets DataFrame with every side priced, model) for one test season."""
    adapter = adapter or _Adapter("player_pass_yds")
    if model is None:
        seasons = sorted(df.season.unique())
        tr = [s for s in seasons if s < season - 1]
        model = adapter.fit(df, names, tr, season - 1)
        base = df[adapter.base_col].fillna(df[adapter.base_col].mean())
        model.mean_model = PY._fit_mean(df[df.season < season][names], (df.y - base)[df.season < season], n_iter=model.n_iter)
    t = df[df.season == season].copy()
    pred = model.predict(t)
    t["mean_raw"], t["sd"] = pred["mean"].values, pred["sd"].values
    t["nname"] = t.player_name.map(_norm)
    ml = lines[lines.season == season]
    cons = ml.groupby(["game_id", "nname"]).line.median().rename("cons_line").reset_index()
    t = t.merge(cons, on=["game_id", "nname"], how="inner")
    # level anchor per week (same rule as cards.py: needs ≥8 matched QBs)
    out = []
    for wk, g in t.groupby("week"):
        gap = float(np.median(g.cons_line - g.mean_raw)) if len(g) >= 8 else 0.0
        g = g.copy()
        g["mean_lvl"] = g.mean_raw + level_w * gap
        g["mean_used"] = (1 - anchor_w) * g.mean_lvl + anchor_w * g.cons_line
        out.append(g)
    t = pd.concat(out)
    # every book/line → both sides
    bl = ml.merge(t[["game_id", "nname", "mean_used", "sd", "y", "player_name"]], on=["game_id", "nname"])
    bl["p_over"] = model.p_over(bl.mean_used.values, bl.sd.values, bl.line.values)
    rows = []
    for side, p, dec, fair in (("Over", bl.p_over, bl.over_dec, bl.over_fair), ("Under", 1 - bl.p_over, bl.under_dec, bl.under_fair)):
        r = bl[["season", "week", "game_id", "nname", "player_name", "bookmaker", "line", "y", "mean_used"]].copy()
        r["side"], r["p"], r["dec"], r["fair"] = side, p.values, dec.values, fair.values
        rows.append(r)
    b = pd.concat(rows, ignore_index=True)
    b["edge"] = b.p - b.fair
    b["ev"] = b.p * (b.dec - 1) - (1 - b.p)
    # best price per (QB, side) — what a card would show
    b = b.sort_values("ev", ascending=False).drop_duplicates(["game_id", "nname", "side"])
    b["win"] = np.where(b.side == "Over", b.y > b.line, b.y < b.line)
    b["push"] = b.y == b.line
    b["pnl"] = np.where(b.push, 0.0, np.where(b.win, b.dec - 1, -1.0))
    return b, model


def summarize(b: pd.DataFrame, thresholds=(0.0, 0.02, 0.04, 0.06, 0.08, 0.10, 0.15)) -> dict:
    out = {}
    for th in thresholds:
        s = b[b.edge >= th]
        n = int(len(s)); w = int(s.win.sum()); p = int(s.push.sum())
        out[f"edge>={th:.2f}"] = {"bets": n, "wins": w, "losses": n - w - p, "pushes": p,
                                  "win_rate": (w / (n - p) if n - p else None), "units": float(s.pnl.sum()),
                                  "roi": (float(s.pnl.sum() / n) if n else None),
                                  "avg_price": (float(s.dec.mean()) if n else None)}
    return out


def run(seasons: list[int] | None = None, grid: bool = True, market: str = "player_pass_yds") -> dict:
    adapter = _Adapter(market)
    lines = main_lines(load_fixtures(seasons), market)
    if lines.empty:
        raise RuntimeError(f"no historical lines for {market}; run `python -m nfl_edge odds_history --markets {market}` first")
    df, names = adapter.load()
    avail = sorted(set(lines.season.unique()) & set(df.season.unique()))
    print(f"[backtest] seasons with closing lines: {avail}; {len(lines)} book-lines")
    res = {"market": market, "seasons": avail, "level_w": LEVEL_ANCHOR_W, "anchor_w": MARKET_ANCHOR_W, "per_season": {}, "by_side": {}, "grid": {}}
    models = {}
    allb = []
    for s in avail:
        b, m = score_season(df, names, lines, s, LEVEL_ANCHOR_W, MARKET_ANCHOR_W, adapter=adapter)
        models[s] = m
        allb.append(b)
        res["per_season"][str(s)] = summarize(b)
        print(f"[backtest] {s}: {len(b)//2} QB-games priced")
    allb = pd.concat(allb, ignore_index=True)
    res["overall"] = summarize(allb)
    for side, g in allb.groupby("side"):
        res["by_side"][side] = summarize(g, (0.0, 0.04, 0.08))
    # calibration at real lines: predicted p vs hit rate
    allb["bucket"] = pd.cut(allb.p, [0, .4, .45, .5, .55, .6, .65, .7, 1.0])
    allb.to_parquet(ROOT / "pipeline" / "artifacts" / f"backtest_{market}.parquet", index=False)
    res["calibration_real_lines"] = [{"bucket": str(k), "n": int(len(g)), "pred": float(g.p.mean()), "actual": float(g.win.mean())}
                                     for k, g in allb[~allb.push].groupby("bucket", observed=True)]
    if grid:
        for lw in (0.0, 0.5, 1.0):
            for aw in (0.0, 0.2, 0.35, 0.5, 0.7):
                gb = pd.concat([score_season(df, names, lines, s, lw, aw, models[s], adapter)[0] for s in avail])
                sm = summarize(gb, (0.02, 0.04, 0.06))
                res["grid"][f"level={lw:.1f},anchor={aw:.2f}"] = sm
                print(f"[grid] level {lw:.1f} anchor {aw:.2f}: " + " | ".join(
                    f"{k[5:]}: {v['bets']}b {v['roi']:+.3f}" if v["roi"] is not None else f"{k[5:]}: 0b" for k, v in sm.items()))
    if market == "player_pass_yds":
        write_md(res)
    return res


def write_md(res: dict):
    p = ROOT / "docs" / "MODEL.md"
    old = p.read_text() if p.exists() else ""
    marker = "\n# MODEL.md — passing yards vs REAL closing lines"
    head, sep, tail = old.partition("\n# MODEL.md — moneyline")
    if marker in head:
        head = head[:head.index(marker)]
    L = [marker, "", f"Run: {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC · seasons {res['seasons']} · "
         f"level anchor {res['level_w']} · player anchor {res['anchor_w']}", "",
         "Closing lines (kickoff − 60 min) from The Odds API historical endpoints, every US book, each book's main line. "
         "Model fit walk-forward (train < S−1, validate S−1, refit mean < S). 1u flat on every side with edge ≥ threshold at the best price.", "",
         "## Overall", "", "| min edge | bets | W-L-P | win rate | units | ROI | avg price |", "|---|---|---|---|---|---|---|"]
    def row(k, r):
        wr = f"{r['win_rate']:.3f}" if r["win_rate"] is not None else "–"
        roi = f"{r['roi']:+.3f}" if r["roi"] is not None else "–"
        ap = f"{r['avg_price']:.3f}" if r["avg_price"] is not None else "–"
        return f"| {k[5:]} | {r['bets']} | {r['wins']}-{r['losses']}-{r['pushes']} | {wr} | {r['units']:+.1f} | {roi} | {ap} |"
    L += [row(k, r) for k, r in res["overall"].items()]
    for s, sm in res["per_season"].items():
        L += ["", f"## {s}", "", "| min edge | bets | W-L-P | win rate | units | ROI | avg price |", "|---|---|---|---|---|---|---|"] + [row(k, r) for k, r in sm.items()]
    L += ["", "## By side (overall)", ""]
    for side, sm in res["by_side"].items():
        L += [f"**{side}**", "", "| min edge | bets | W-L-P | win rate | units | ROI | avg price |", "|---|---|---|---|---|---|---|"] + [row(k, r) for k, r in sm.items()] + [""]
    L += ["## Calibration at real lines", "", "| model p bucket | n | mean p | hit rate |", "|---|---|---|---|"]
    L += [f"| {c['bucket']} | {c['n']} | {c['pred']:.3f} | {c['actual']:.3f} |" for c in res["calibration_real_lines"]]
    if res["grid"]:
        L += ["", "## Anchor-weight grid (ROI at edge ≥ 4%, all seasons)", "", "| level \\ player anchor | " + " | ".join(k.split("anchor=")[1] for k in list(res["grid"])[:5]) + " |", "|---|" + "---|" * 5]
        for lw in ("0.0", "0.5", "1.0"):
            cells = []
            for k, v in res["grid"].items():
                if k.startswith(f"level={lw}"):
                    r = v["edge>=0.04"]
                    cells.append(f"{r['roi']:+.3f} ({r['bets']})" if r["roi"] is not None else "–")
            L.append(f"| {lw} | " + " | ".join(cells) + " |")
    p.write_text(head.rstrip() + "\n" + "\n".join(L) + "\n" + (sep + tail if sep else ""))
