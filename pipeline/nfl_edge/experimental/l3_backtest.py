"""Fit the L3 experiment's empirical-Bayes priors and projection models, then backtest naive_v0 vs l3_v1 against
real closing prop lines (pipeline/fixtures/odds_history). No database, no credits:

    python -m nfl_edge backtest_l3            # ~5 min the first time (downloads nflverse 2015→ pbp/weekly to .cache)

Writes nfl_edge/experimental/l3_params.json (read by the weekly job) and docs/L3_BACKTEST.md (generated tables).
Walk-forward: every test season's projector is fitted on seasons strictly before it; the EB priors are fitted on
2016–2025 as the brief says (they're variance components, not betting signals — see DECISIONS #45 for the caveat).
"""
from __future__ import annotations
import json
import math
from pathlib import Path
import numpy as np
import pandas as pd
from ..config import ROOT
from ..sources import nflverse
from ..ingest.odds_history import load_fixtures
from ..models.backtest_lines import main_lines
from . import l3

PARAMS_PATH = Path(__file__).with_name("l3_params.json")
REPORT_PATH = ROOT / "docs" / "L3_BACKTEST.md"
FIT_SEASONS = list(range(2016, 2026))
PBP_COLS = ["game_id", "season", "week", "season_type", "posteam", "defteam", "play_type", "pass", "rush", "qb_dropback",
            "qb_scramble", "sack", "yards_gained", "passing_yards", "rushing_yards", "epa", "success"]


def load_inputs(first: int = 2015, last: int = 2025):
    pbp = pd.concat([pd.read_parquet(nflverse.fetch("pbp", y), columns=PBP_COLS) for y in range(first, last + 1)])
    ws = pd.concat([pd.read_parquet(nflverse.fetch("weekly_stats", y)) for y in range(first, last + 1)])
    games = pd.read_csv(nflverse.fetch("schedules"))
    games = games[(games.game_type == "REG") & games.season.between(first, last)]
    from ..teams import norm
    for c in ("home_team", "away_team"):
        games[c] = games[c].map(norm)
    for c in ("posteam", "defteam"):
        pbp[c] = pbp[c].map(lambda x: norm(x) if isinstance(x, str) else x)
    ws["team"] = ws.team.map(lambda x: norm(x) if isinstance(x, str) else x)
    return pbp, ws, games


# ------------------------------------------------------------------ EB fit
def fit_eb(tg: pd.DataFrame, sigma2: dict, seasons=FIT_SEASONS) -> tuple[dict, pd.DataFrame]:
    """rho (how much prior info predicts L3) and tau² (true-talent variance of L3 around that prior), per stat, by
    method of moments over every (season, week ≥ 2) defense-L3 in the fit window. Also returns the panel used, with
    each defense's NEXT game per-play deviation, so the shrinkage can be validated out of sample."""
    rows = []
    for s in seasons:
        for w in range(2, 19):
            t = l3.defense_table(tg, s, w)
            if t.empty:
                continue
            nxt = tg[(tg.season == s) & (tg.week == w)]
            t = t.merge(nxt.rename(columns={"defteam": "team"}).drop(columns=["season", "week", "game_id", "posteam"])
                        .add_prefix("next_").rename(columns={"next_team": "team"}), on="team", how="left")
            rows.append(t)
    panel = pd.concat(rows, ignore_index=True)
    params = {}
    for st, (num, den, _) in l3.STATS.items():
        p = panel[(panel[f"{st}_n"] > 0) & panel[f"{st}_adj"].notna()]
        x, y, n = p[f"{st}_prior_dev"].values, p[f"{st}_adj"].values, p[f"{st}_n"].values
        rho = float(np.sum(n * x * y) / np.sum(n * x * x)) if np.sum(n * x * x) > 0 else 0.0
        resid = y - rho * x
        tau2 = float(np.average(resid ** 2, weights=n) - np.average(sigma2[st] / n, weights=n))
        params[st] = {"rho": rho, "tau2": max(tau2, 1e-6), "sigma2": sigma2[st]}
    return params, panel


def validate_eb(panel: pd.DataFrame, params: dict, tg: pd.DataFrame) -> dict:
    """Does the shrunk L3 predict the defense's next game better than raw L3? (MSE on next-game per-play deviation
    from that week's league rate, weighted by next-game plays.)"""
    out = {}
    for st, (num, den, _) in l3.STATS.items():
        p = panel[panel[f"next_{den}"].fillna(0) > 0].copy()
        nxt = p[f"next_{num}"] / p[f"next_{den}"] - p[f"{st}_league"]
        pr = params[st]
        noise = pr["sigma2"] / p[f"{st}_n"].clip(lower=1)
        B = pr["tau2"] / (pr["tau2"] + noise)
        mu = pr["rho"] * p[f"{st}_prior_dev"]
        shr = mu + B * (p[f"{st}_adj"] - mu)
        rawdev = p[f"{st}_raw"] - p[f"{st}_league"]
        w = p[f"next_{den}"]
        mse = lambda e: float(np.average((nxt - e) ** 2, weights=w))
        out[st] = {"n": int(len(p)), "mse_zero": mse(0 * nxt), "mse_raw_l3": mse(rawdev), "mse_adj_l3": mse(p[f"{st}_adj"]),
                   "mse_shrunk": mse(shr), "mean_shrink": float(B.mean())}
    return out


# ------------------------------------------------------------------ player panel
def player_panel(ws, tg, games, eb, seasons, markets=(l3.PASS_MKT, l3.RUSH_MKT)) -> dict[str, pd.DataFrame]:
    ctx = l3.game_context(games)
    out = {m: [] for m in markets}
    hists = {m: l3.player_history(ws, l3.MARKETS[m]) for m in markets}
    for s in seasons:
        for w in range(2, 19):
            dtab = l3.defense_table(tg, s, w, eb)
            if dtab.empty:
                continue
            for m in markets:
                mk = l3.MARKETS[m]
                h = hists[m]
                fr = l3.feature_rows(h, tg, ctx, mk, s, w, eb, dtab=dtab)
                if fr.empty:
                    continue
                act = h[(h.season == s) & (h.week == w)][["player_id", mk.yds, mk.vol]].rename(
                    columns={mk.yds: "actual_yds", mk.vol: "actual_vol"})
                fr = fr.merge(act, on="player_id", how="left")
                out[m].append(fr)
    return {m: pd.concat(v, ignore_index=True) if v else pd.DataFrame() for m, v in out.items()}


def consensus_lines(lines: pd.DataFrame, market: str) -> pd.DataFrame:
    """Per (game, player): the modal line among bettable books, best Over/Under price at that line, mean no-vig."""
    ml = main_lines(lines, market)
    if ml.empty:
        return ml
    rows = []
    for (gid, nn), g in ml.groupby(["game_id", "nname"]):
        mode = g.line.mode().sort_values()
        line = float(mode.iloc[(len(mode) - 1) // 2]) if len(mode) else float(g.line.iloc[0])   # an actual posted line
        at = g[g.line == line]
        bo, bu = at.loc[at.over_dec.idxmax()], at.loc[at.under_dec.idxmax()]
        rows.append({"season": int(g.season.iloc[0]), "week": int(g.week.iloc[0]), "game_id": gid, "nname": nn, "line": line,
                     "over_dec": float(bo.over_dec), "over_book": bo.bookmaker, "under_dec": float(bu.under_dec),
                     "under_book": bu.bookmaker, "fair_over": float(at.over_fair.mean()), "n_books": int(len(at))})
    return pd.DataFrame(rows)


def _grade(side, line, actual, dec):
    if actual == line:
        return "push", 0.0
    won = actual > line if side == "Over" else actual < line
    return ("win", dec - 1) if won else ("loss", -1.0)


def score_backtest(panel: pd.DataFrame, cons: pd.DataFrame, proj: l3.Projector, market: str) -> pd.DataFrame:
    """Every priced player-game in the test season, with both versions' verdicts and grades."""
    p = panel.copy()
    p["nname"] = p.name.map(l3.norm_name)
    b = cons.merge(p, on=["season", "week", "game_id", "nname"], how="inner")
    b = b[b.actual_vol.fillna(0) > 0]                 # no usage → the book voids the prop
    if market == l3.RUSH_MKT:
        b = l3.rb1_only(b)
    b["proj"] = proj.project(b).values
    b["p_over"] = proj.p_over(b.proj.values, b.line.values)
    rows = []
    for _, r in b.iterrows():
        nv = l3.naive_verdict(r.line, r.naive_l3, r.naive_n, r.naive_cond or "")
        ng = l3.naive_g10_verdict(r.line, r.naive_l3, r.naive_n, r.naive_cond or "")
        vv, edge = l3.v1_verdict(r.p_over, r.fair_over, r.v1_cond or "")
        base = {"season": r.season, "week": r.week, "game_id": r.game_id, "player": r["name"], "market": market,
                "line": r.line, "actual": r.actual_yds, "p_over": r.p_over, "fair_over": r.fair_over, "proj": r.proj,
                "naive_l3": r.naive_l3, "def_cond_naive": r.naive_cond, "def_cond_v1": r.v1_cond, "went_over": r.actual_yds > r.line,
                "gap": l3.naive_gap(r.line, r.naive_l3)}
        for ver, side, e in (("naive_v0", nv, None), ("naive_g10", ng, None), ("l3_v1", vv, edge)):
            if side is None:
                continue
            dec = r.over_dec if side == "Over" else r.under_dec
            res, pnl = _grade(side, r.line, r.actual_yds, dec)
            _, pnl110 = _grade(side, r.line, r.actual_yds, l3.FLAT_DEC)
            rows.append({**base, "version": ver, "side": side, "dec": dec, "edge": e, "result": res, "pnl": pnl, "pnl_110": pnl110})
        rows.append({**base, "version": "_all", "side": None, "dec": None, "edge": None, "result": None, "pnl": None})
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ main
def run(write: bool = True, use_cache: bool = False) -> dict:
    pbp, ws, games = load_inputs()
    tg = l3.team_games(pbp)
    sigma2 = l3.play_variances(pbp[pbp.season.isin(FIT_SEASONS)])
    eb, panel = fit_eb(tg, sigma2)
    val = validate_eb(panel, eb, tg)
    print("[l3] EB params", json.dumps(eb, indent=1))
    print("[l3] EB validation", json.dumps(val, indent=1))
    cache = ROOT / "pipeline" / "artifacts" / "l3_player_panel.pkl"
    if use_cache and cache.exists():
        pp = pd.read_pickle(cache)
    else:
        pp = player_panel(ws, tg, games, eb, FIT_SEASONS)
        pd.to_pickle(pp, cache)

    lines = load_fixtures()
    results, bets_all, calib = {}, [], {}
    projectors_live = {}
    for m, panel_m in pp.items():
        mk = l3.MARKETS[m]
        cons = consensus_lines(lines, m)
        test_seasons = sorted(cons.season.unique()) if len(cons) else []
        for T in test_seasons:
            train = panel_m[(panel_m.season < T) & panel_m.actual_vol.notna()]
            proj = l3.Projector(m).fit(train, mk)
            bt = score_backtest(panel_m[panel_m.season == T], cons[cons.season == T], proj, m)
            bets_all.append(bt)
        projectors_live[m] = l3.Projector(m).fit(panel_m[panel_m.actual_vol.notna()], mk).to_json()
    bets = pd.concat(bets_all, ignore_index=True) if bets_all else pd.DataFrame()
    if len(bets):
        bets = bets[bets.week >= l3.BACKTEST_MIN_WEEK]       # L3 needs 3 games played (Haywood, 2026-10-04)

    summary = {}
    if len(bets):
        allrows = bets[bets.version == "_all"]
        for m in allrows.market.unique():
            a = allrows[allrows.market == m]
            summary[f"base_rate_over|{m}"] = {"n": int(len(a)), "over_rate": float(a.went_over.mean())}
            # calibration of l3_v1 P(over) in deciles over every priced line
            a = a.assign(dec=pd.qcut(a.p_over, 10, labels=False, duplicates="drop"))
            calib[m] = [{"decile": int(d), "n": int(len(g)), "p_mean": float(g.p_over.mean()), "hit": float(g.went_over.mean())}
                        for d, g in a.groupby("dec")]
        flagged = bets[bets.version != "_all"]
        flat = flagged.assign(pnl=flagged.pnl_110)
        for keys, g in flat.groupby(["version", "market"]):
            summary["flat110|" + "|".join(keys)] = l3.summarize_bets(g)
            for side, gs in g.groupby("side"):
                summary["flat110|" + "|".join(keys) + f"|{side}"] = l3.summarize_bets(gs)
        for v, g in flat.groupby("version"):
            summary[f"flat110|{v}|all"] = l3.summarize_bets(g)
        for keys, g in flagged.groupby(["version", "market"]):
            summary["|".join(keys)] = l3.summarize_bets(g)
            for side, gs in g.groupby("side"):
                summary["|".join(keys) + f"|{side}"] = l3.summarize_bets(gs)
            for s, gs in g.groupby("season"):
                summary["|".join(keys) + f"|{int(s)}"] = l3.summarize_bets(gs)
        for v, g in flagged.groupby("version"):
            summary[f"{v}|all"] = l3.summarize_bets(g)

    lean = {f"{v}|{m}": l3.lean_eligible(summary.get(f"{v}|{m}", {})) for v in l3.VERSIONS for m in l3.MARKETS}
    params = {"eb": eb, "eb_validation": val, "projectors": projectors_live, "backtest": summary, "calibration": calib,
              "lean_eligible": lean, "fit_seasons": FIT_SEASONS,
              "lines_available": {m: sorted(int(x) for x in consensus_lines(lines, m).season.unique()) for m in l3.MARKETS},
              "generated_at": pd.Timestamp.utcnow().isoformat()}
    if write:
        PARAMS_PATH.write_text(json.dumps(params, indent=1, default=float))
        write_report(params)
        bets.to_csv(ROOT / "pipeline" / "artifacts" / "l3_backtest_bets.csv", index=False)
    return params


def _fmt(s: dict | None) -> str:
    if not s or not s.get("n"):
        return "| – | – | – | – | – | – |"
    pct = lambda x: "–" if x is None else f"{x * 100:+.1f}%"
    return (f"| {s['w']}-{s['l']}-{s['p']} | {s['hit'] * 100:.1f}% | {pct(s['roi'])} | {s['units']:+.1f}u | "
            f"[{pct(s['ci_lo'])}, {pct(s['ci_hi'])}] | {s['t']:.2f} |" if s.get("t") is not None else
            f"| {s['w']}-{s['l']}-{s['p']} | {s['hit'] * 100:.1f}% | {pct(s['roi'])} | {s['units']:+.1f}u | – | – |")


def write_report(p: dict):
    b = p["backtest"]
    L = ["# L3 experiment — generated backtest (do not edit; `python -m nfl_edge backtest_l3`)", "",
         f"Generated {p['generated_at'][:16]} UTC. Closing lines from `pipeline/fixtures/odds_history`, DK/FD/Pinnacle only, "
         "graded at the best closing price among those books at the modal line. Opening prices are not in the fixtures, "
         "so there is no opening-price grade or backtest CLV yet.", "",
         f"Lines available: {json.dumps(p['lines_available'])}", "",
         "## Base rate (share of priced lines that went Over)", "", "| market | lines | over rate |", "|---|---|---|"]
    for k, v in b.items():
        if k.startswith("base_rate_over|"):
            L.append(f"| {k.split('|')[1]} | {v['n']} | {v['over_rate'] * 100:.1f}% |")
    L += ["", f"Every row: weeks ≥ {l3.BACKTEST_MIN_WEEK} only (the last-3 inputs need 3 games played).", ""]
    L += ["", "## Results at a flat −110 on every pick (1u)", "", "| version · market · split | W-L-P | hit | ROI | units | 95% CI ROI | t |",
          "|---|---|---|---|---|---|---|"]
    for k in sorted(k for k in b if k.startswith("flat110|")):
        L.append(f"| {k[8:].replace('|', ' · ')} " + _fmt(b[k]))
    L += ["", "## Results (1u flat, best actual closing price)", "", "| version · market · split | W-L-P | hit | ROI | units | 95% CI ROI | t |",
          "|---|---|---|---|---|---|---|"]
    for k in sorted(k for k in b if not k.startswith(("base_rate", "flat110"))):
        L.append(f"| {k.replace('|', ' · ')} " + _fmt(b[k]))
    L += ["", "## Calibration of l3_v1 P(over), deciles over every priced line", ""]
    for m, rows in p["calibration"].items():
        L += [f"**{m}**", "", "| decile | n | mean P(over) | actual over |", "|---|---|---|---|"]
        L += [f"| {r['decile'] + 1} | {r['n']} | {r['p_mean'] * 100:.1f}% | {r['hit'] * 100:.1f}% |" for r in rows]
        L.append("")
    L += ["## Empirical-Bayes shrinkage (fit 2016–2025)", "", "| stat | rho (prior weight) | tau² | σ² per play | mean shrink B | MSE raw L3 | MSE adj L3 | MSE shrunk | MSE league avg |",
          "|---|---|---|---|---|---|---|---|---|"]
    for st, e in p["eb"].items():
        v = p["eb_validation"][st]
        L.append(f"| {st} | {e['rho']:.3f} | {e['tau2']:.4f} | {e['sigma2']:.3f} | {v['mean_shrink']:.2f} | {v['mse_raw_l3']:.4f} | "
                 f"{v['mse_adj_l3']:.4f} | {v['mse_shrunk']:.4f} | {v['mse_zero']:.4f} |")
    L += ["", "## Publishing rule", "", f"`lean` requires ≥{l3.LEAN_MIN_BETS} graded backtest bets and a 95% CI lower bound on ROI above "
          f"{l3.LEAN_MIN_CI_LO * 100:.0f}%. Current: `{json.dumps(p['lean_eligible'])}`."]
    REPORT_PATH.write_text("\n".join(L) + "\n")
