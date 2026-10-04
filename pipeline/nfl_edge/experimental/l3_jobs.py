"""DB jobs for the L3 experiment: score (Tue after the open snapshot, Sun 9am ET) and grade (with the card grader).

    python -m nfl_edge score_l3_experiment [--week N] [--label L]
    python -m nfl_edge grade_l3_experiment

Graceful degradation: a missing source (TeamRankings, injuries, odds) is labelled on the rows; it never raises out
of the scheduled jobs (cli.py wraps these in try/except).
"""
from __future__ import annotations
import datetime as dt
import json
import re
import numpy as np
import pandas as pd
import requests
from .. import db
from ..config import is_bettable
from ..ingest.odds_jobs import target_week
from . import l3
from .l3_backtest import PARAMS_PATH

TR_URLS = {"pass": "https://www.teamrankings.com/nfl/stat/opponent-passing-yards-per-game",
           "rush": "https://www.teamrankings.com/nfl/stat/opponent-rushing-yards-per-game"}
TR_NAMES = {"Seattle": "SEA", "New England": "NE", "NY Jets": "NYJ", "LA Rams": "LA", "Carolina": "CAR", "Kansas City": "KC",
            "Tennessee": "TEN", "Philadelphia": "PHI", "Las Vegas": "LV", "Green Bay": "GB", "Tampa Bay": "TB", "Chicago": "CHI",
            "Dallas": "DAL", "San Francisco": "SF", "Pittsburgh": "PIT", "New Orleans": "NO", "Baltimore": "BAL",
            "NY Giants": "NYG", "Miami": "MIA", "LA Chargers": "LAC", "Minnesota": "MIN", "Arizona": "ARI", "Cleveland": "CLE",
            "Jacksonville": "JAX", "Denver": "DEN", "Houston": "HOU", "Buffalo": "BUF", "Cincinnati": "CIN", "Atlanta": "ATL",
            "Indianapolis": "IND", "Washington": "WAS", "Detroit": "DET"}
TR_TOLERANCE = 2.0
STAT_COLS = {l3.PASS_MKT: ("passing_yards", "attempts"), l3.RUSH_MKT: ("rushing_yards", "carries")}


def load_params() -> dict:
    if PARAMS_PATH.exists():
        return json.loads(PARAMS_PATH.read_text())
    print("[l3] l3_params.json missing — using DEFAULT_PARAMS, no projector (run backtest_l3)")
    return {"eb": l3.DEFAULT_PARAMS, "projectors": {}, "lean_eligible": {}}


# ------------------------------------------------------------------ TeamRankings cross-check
def parse_teamrankings(html: str) -> dict[str, float]:
    """team abbr → 'Last 3' value from a TeamRankings stat page (columns: Rank, Team, <season>, Last 3, Last 1, …)."""
    from bs4 import BeautifulSoup
    t = BeautifulSoup(html, "html.parser").select_one("table.tr-table")
    out = {}
    if t is None:
        return out
    for tr in t.select("tbody tr"):
        td = [x.get_text(strip=True) for x in tr.find_all("td")]
        if len(td) >= 4 and td[1] in TR_NAMES:
            try:
                out[TR_NAMES[td[1]]] = float(td[3])
            except ValueError:
                pass
    return out


def fetch_teamrankings() -> dict[str, dict[str, float]] | None:
    try:
        h = {"User-Agent": "Mozilla/5.0 (nfl-edge-finder weekly cross-check; 2 requests/week)"}
        out = {k: parse_teamrankings(requests.get(u, headers=h, timeout=30).text) for k, u in TR_URLS.items()}
        return out if all(len(v) >= 30 for v in out.values()) else None
    except Exception as e:
        print(f"[l3] TeamRankings cross-check unavailable: {e}")
        return None


# ------------------------------------------------------------------ lines
def _week_lines(season: int, week: int, market: str) -> tuple[pd.DataFrame, int | None]:
    snap = db.read_sql("""SELECT id FROM odds_snapshots WHERE season=:s AND week=:w AND :m = ANY(markets)
                          ORDER BY taken_at DESC LIMIT 1""", {"s": season, "w": week, "m": market})
    if snap.empty:
        return pd.DataFrame(), None
    sid = int(snap.id.iloc[0])
    l = db.read_sql("""SELECT l.*, e.game_id FROM odds_lines l JOIN odds_events e USING (event_id)
                       WHERE l.snapshot_id=:id AND l.market=:m""", {"id": sid, "m": market})
    return l[l.bookmaker.map(is_bettable)], sid


def consensus_live(l: pd.DataFrame) -> pd.DataFrame:
    """Per (game, player): modal line among bettable books; best price per side at that line; mean no-vig P(over)."""
    if l.empty:
        return pd.DataFrame()
    l = l.copy()
    l["nname"] = l.player.map(l3.norm_name)
    o = l[l.side == "Over"][["game_id", "nname", "player", "player_id", "bookmaker", "line", "price_decimal", "price_american"]]
    u = l[l.side == "Under"][["game_id", "nname", "bookmaker", "line", "price_decimal", "price_american"]]
    two = o.merge(u, on=["game_id", "nname", "bookmaker", "line"], suffixes=("_o", "_u"))
    if two.empty:
        return two
    po, pu = 1 / two.price_decimal_o, 1 / two.price_decimal_u
    two["fair_over"] = po / (po + pu)
    rows = []
    for (gid, nn), g in two.groupby(["game_id", "nname"]):
        mode = g.line.mode().sort_values()
        line = float(mode.iloc[(len(mode) - 1) // 2])
        at = g[g.line == line]
        bo, bu = at.loc[at.price_decimal_o.idxmax()], at.loc[at.price_decimal_u.idxmax()]
        rows.append({"game_id": gid, "nname": nn, "player": g.player.iloc[0], "odds_player_id": g.player_id.dropna().iloc[0] if g.player_id.notna().any() else None,
                     "line": line, "fair_over": float(at.fair_over.mean()), "n_books": int(len(at)),
                     "over_dec": float(bo.price_decimal_o), "over_am": int(bo.price_american_o), "over_book": bo.bookmaker,
                     "under_dec": float(bu.price_decimal_u), "under_am": int(bu.price_american_u), "under_book": bu.bookmaker,
                     "book_prices": [{"book": r.bookmaker, "line": float(r.line), "over": int(r.price_american_o), "under": int(r.price_american_u)}
                                     for r in g.itertuples()]})
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ factors (same shape as main cards)
def _ord(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def build_factors(r: dict, market: str, version: str, side: str | None) -> list[dict]:
    word = "passing" if market == l3.PASS_MKT else "rushing"
    unit = "dropback" if market == l3.PASS_MKT else "designed carry"
    f = []
    if r.get("naive_n"):
        f.append({"factor": "player_l3", "value": r["naive_l3"],
                  "impact": "+" if (side == "Over" and r["line"] < r["naive_l3"]) or (side == "Under" and r["line"] > r["naive_l3"]) else "=",
                  "text": f"{r['name']} averaged {r['naive_l3']:.1f} {word} yds over his last {r['naive_n']} ({r['naive_games']}); line {r['line']}",
                  "source": {"table": "raw_weekly_stats"}})
    if version == "naive_g10" and r.get("gap") == r.get("gap") and r.get("gap") is not None:
        ok = abs(r["gap"]) >= l3.NAIVE_GATE
        f.append({"factor": "gap_gate", "value": r["gap"], "impact": "+" if ok and side else "−",
                  "text": f"L3 vs line gap {r['gap'] * 100:+.1f}% of the line — {'passes' if ok else 'fails'} the {l3.NAIVE_GATE * 100:.0f}% gate"})
    imp = {"soft": "+" if side == "Over" else "=", "stingy": "+" if side == "Under" else "="}
    f.append({"factor": "def_l3_ypg", "value": r["def_ypg_l3"], "impact": imp.get(r.get("naive_cond") or "", "="),
              "text": f"{r['opp']} allowed {r['def_ypg_l3']:.1f} {word} yds/g over its last {int(r['def_l3_games'])} — {_ord(int(r['naive_rank']))} of 32 (1st = fewest)"
                      + (f" ({r['naive_cond']})" if r.get("naive_cond") else ""),
              "source": {"table": "experimental_l3_defense", "key": r["opp"]}})
    if version == "l3_v1":
        f.append({"factor": "def_l3_eff", "value": r["def_dev"], "impact": imp.get(r.get("v1_cond") or "", "="),
                  "text": f"{r['opp']} per {unit}: raw L3 {r['def_raw']:.2f}, opponent-adjusted {r['def_adj']:+.2f} vs expectation, "
                          f"shrunk {r['def_dev']:+.2f} (B={r['def_shrink']:.2f}, z={r['def_z']:+.2f})"
                          + (f" → {r['v1_cond']}" if r.get("v1_cond") else " → no condition"),
                  "source": {"table": "experimental_l3_defense", "key": r["opp"]}})
        if r.get("proj") is not None:
            f.append({"factor": "projection", "value": r["proj"], "impact": "+" if side else "=",
                      "text": f"Projection {r['proj']:.1f} (P25 {r['p25']:.0f} · P75 {r['p75']:.0f}); P(over {r['line']}) {r['p_over'] * 100:.0f}% vs market {r['fair_over'] * 100:.0f}%"})
        if r.get("wind_hi"):
            f.append({"factor": "weather", "value": r.get("wind"), "impact": "−" if side == "Over" and market == l3.PASS_MKT else "=",
                      "text": f"Wind {r.get('wind'):.0f} mph forecast (≥15)"})
    if r.get("injury_status") in l3.INJURY_FLAGGED:
        f.append({"factor": "injury", "value": r["injury_status"], "impact": "−",
                  "text": f"{r['name']} is listed {r['injury_status']} — {'flag suppressed' if r['injury_status'] in ('Out', 'Doubtful') else 'status not final'}"})
    return f


# ------------------------------------------------------------------ voids (append-only correction log)
def _void_ineligible(season: int, week: int, market: str, eligible: set) -> int:
    """Flags already written this week for players who are no longer eligible (e.g. RB2s scored before the RB1 rule,
    DECISIONS #48) are voided in experimental_l3_voids. The flag rows themselves are never edited or deleted; the
    page and the ledger skip voided flags."""
    old = db.read_sql("""SELECT f.id, f.player_id FROM experimental_l3_flags f
                         LEFT JOIN experimental_l3_voids v ON v.flag_id = f.id
                         WHERE f.season=:s AND f.week=:w AND f.market=:m AND v.id IS NULL""",
                      {"s": season, "w": week, "m": market})
    bad = old[~old.player_id.isin(eligible)]
    if bad.empty:
        return 0
    rows = pd.DataFrame({"flag_id": bad.id.astype(int), "reason": "not RB1 (highest rushing line on his team) — DECISIONS #48"})
    n = db.upsert(rows, "experimental_l3_voids", ["flag_id"], update=False)
    print(f"[l3] voided {n} {market} rows for non-RB1 players")
    return n


# ------------------------------------------------------------------ score
def score_l3_experiment(week: int | None = None, label: str = "manual") -> int:
    season, wk = target_week()
    wk = week or wk
    params = load_params()
    eb = params.get("eb") or l3.DEFAULT_PARAMS
    now = dt.datetime.now(dt.timezone.utc)
    with db.JobRun("score_l3_experiment") as run:
        pbp = db.read_sql(f"""SELECT {', '.join(c for c in ['game_id','season','week','season_type','posteam','defteam','play_type','pass','rush',
                              'qb_dropback','qb_scramble','sack','yards_gained','passing_yards','rushing_yards','epa','success'])}
                              FROM raw_pbp WHERE season IN (:a, :b) AND season_type='REG'""", {"a": season - 1, "b": season})
        tg = l3.team_games(pbp)
        if params.get("generated_at"):
            db.upsert(pd.DataFrame([{"generated_at": params["generated_at"], "backtest": params.get("backtest", {}),
                                     "lean_eligible": params.get("lean_eligible", {}), "eb": eb,
                                     "eb_validation": params.get("eb_validation", {})}]),
                      "experimental_l3_meta", ["generated_at"], update=False)
        dtab = l3.defense_table(tg, season, wk, eb)
        if dtab.empty:
            print(f"[l3] no {season} games before week {wk}; nothing to do"); run.rows = 0; return 0
        games = db.read_sql("""SELECT game_id, season, week, home_team, away_team, kickoff_utc, spread_line, total_line, roof, wind
                               FROM raw_games WHERE season IN (:a, :b) AND game_type='REG'""", {"a": season - 1, "b": season})
        used = games[(games.season == season) & (games.week < wk)]
        as_of = pd.to_datetime(used.kickoff_utc, utc=True).max()
        first_kick = pd.to_datetime(games[(games.season == season) & (games.week == wk)].kickoff_utc, utc=True).min()
        assert as_of < first_kick, "point-in-time violation: defense table uses a game at/after this week's first kickoff"

        # TeamRankings cross-check (warning only)
        tr = fetch_teamrankings()
        drows = []
        n_mismatch = 0
        for _, t in dtab.iterrows():
            status, trp, trr = "unavailable", None, None
            if tr:
                trp, trr = tr["pass"].get(t.team), tr["rush"].get(t.team)
                ok = trp is not None and trr is not None and abs(trp - t.pass_ypg_l3) <= TR_TOLERANCE and abs(trr - t.rush_ypg_l3) <= TR_TOLERANCE
                status = "ok" if ok else "mismatch"
                n_mismatch += not ok
            stats = {s: {k: (None if pd.isna(t.get(f"{s}_{k}")) else float(t.get(f"{s}_{k}")))
                         for k in ("raw", "adj", "shrunk", "shrink", "sd", "z", "rank", "n", "league", "prior")} for s in l3.STATS}
            drows.append({"run_label": label, "season": season, "week": wk, "team": t.team, "as_of": as_of, "games": t.games,
                          "l3_games": t.l3_games, "l3_opps": t.l3_opps, "pass_ypg_l3": t.pass_ypg_l3, "rush_ypg_l3": t.rush_ypg_l3,
                          "tr_pass_l3": trp, "tr_rush_l3": trr, "tr_status": status,
                          "pass_naive_rank": t.pass_naive_rank, "pass_naive_cond": t.pass_naive_cond,
                          "rush_naive_rank": t.rush_naive_rank, "rush_naive_cond": t.rush_naive_cond,
                          "pass_v1_cond": t.pass_v1_cond, "rush_v1_cond": t.rush_v1_cond, "stats": stats})
        db.upsert(pd.DataFrame(drows), "experimental_l3_defense", ["season", "week", "team", "run_label"], update=False)
        if tr is None:
            print("[l3] WARNING TeamRankings cross-check unavailable")
        elif n_mismatch:
            # TR updates as games finish, so Thursday/Sunday-AM runs legitimately differ for teams that already played this week
            print(f"[l3] WARNING {n_mismatch} teams differ from TeamRankings 'Last 3' by > ±{TR_TOLERANCE} yd/g")

        ws = db.read_sql("""SELECT player_id, player_name, position, season, week, season_type, team, opponent_team,
                                   attempts, passing_yards, carries, rushing_yards
                            FROM raw_weekly_stats WHERE season IN (:a, :b) AND season_type='REG'""", {"a": season - 1, "b": season})
        ctx = l3.game_context(games)
        inj = db.read_sql("""SELECT DISTINCT ON (gsis_id) gsis_id, report_status FROM raw_injuries
                             WHERE season=:s AND week=:w ORDER BY gsis_id, observed_at DESC""", {"s": season, "w": wk})
        inj = dict(zip(inj.gsis_id, inj.report_status)) if len(inj) else {}

        out = []
        for market in (l3.PASS_MKT, l3.RUSH_MKT):
            mk = l3.MARKETS[market]
            lines, snap_id = _week_lines(season, wk, market)
            if lines.empty:
                print(f"[l3] no {market} lines for {season} wk{wk}"); continue
            cons = consensus_live(lines)
            fr = l3.feature_rows(l3.player_history(ws, mk), tg, ctx, mk, season, wk, eb, dtab=dtab)
            if fr.empty:
                continue
            fr["nname"] = fr.name.map(l3.norm_name)
            b = cons.merge(fr, on=["game_id", "nname"], how="inner")
            b = b[pd.to_datetime(b.kickoff_utc, utc=True) > now]          # never write a flag after kickoff
            if market == l3.RUSH_MKT:
                b = l3.rb1_only(b)
                _void_ineligible(season, wk, market, set(b.player_id))
            pj = params.get("projectors", {}).get(market)
            proj = l3.Projector.from_json(pj) if pj else None
            if proj is not None and len(b):
                b["proj"] = proj.project(b).values
                b["p_over"] = proj.p_over(b.proj.values, b.line.values)
            for _, r in b.iterrows():
                r = r.to_dict()
                r["injury_status"] = inj.get(r["player_id"])
                r["gap"] = l3.naive_gap(r["line"], r["naive_l3"])
                if proj is not None:
                    r["p25"], _, r["p75"] = proj.quantiles(r["proj"])
                blocked = r["injury_status"] in ("Out", "Doubtful")
                for version in l3.VERSIONS:
                    if version in ("naive_v0", "naive_g10"):
                        fn = l3.naive_verdict if version == "naive_v0" else l3.naive_g10_verdict
                        side = fn(r["line"], r["naive_l3"], r["naive_n"], r.get("naive_cond") or "")
                        edge, model_prob, cond = None, None, r.get("naive_cond") or ""
                    else:
                        if proj is None:
                            continue
                        side, edge = l3.v1_verdict(r["p_over"], r["fair_over"], r.get("v1_cond") or "")
                        model_prob = (r["p_over"] if side == "Over" else 1 - r["p_over"]) if side else None
                        cond = r.get("v1_cond") or ""
                    if blocked:
                        side = None
                    dec = (r["over_dec"] if side == "Over" else r["under_dec"]) if side else None
                    am = (r["over_am"] if side == "Over" else r["under_am"]) if side else None
                    bk = (r["over_book"] if side == "Over" else r["under_book"]) if side else None
                    lean = bool(params.get("lean_eligible", {}).get(f"{version}|{market}"))
                    out.append({
                        "run_label": label, "version": version, "season": season, "week": wk, "game_id": r["game_id"],
                        "kickoff_utc": r["kickoff_utc"], "player_id": r["player_id"], "player_name": r["name"],
                        "position": r["position"], "team": r["team"], "opponent": r["opp"], "market": market, "side": side,
                        "line": r["line"], "price_american": am, "price_decimal": dec, "book": bk, "snapshot_id": snap_id,
                        "fair_over": r["fair_over"],
                        "market_prob": (r["fair_over"] if side == "Over" else 1 - r["fair_over"]) if side else None,
                        "model_prob": model_prob, "edge": None if edge is None or edge != edge else float(edge),
                        "p_over": r.get("p_over"), "projection": r.get("proj"), "proj_p25": r.get("p25"), "proj_p75": r.get("p75"),
                        "player_l3": r["naive_l3"], "player_l3_games": r["naive_games"], "def_cond": cond,
                        "tag": "lean" if (lean and side) else "watch", "injury_status": r["injury_status"],
                        "factors": build_factors(r, market, version, side),
                        "inputs": {k: (None if (isinstance(v, float) and v != v) else v) for k, v in r.items()
                                   if k in ("rate_l3", "rate_season", "rate_prev", "vol_l3", "vol_season", "implied", "team_spread",
                                            "dome", "wind_hi", "wind", "def_dev", "def_sd", "def_z", "def_raw", "def_adj", "def_shrink",
                                            "def_ypg_l3", "naive_rank", "naive_n", "gap", "n_books", "book_prices")},
                    })
        df = pd.DataFrame(out)
        run.rows = db.upsert(df, "experimental_l3_flags", ["version", "season", "week", "player_id", "market", "snapshot_id"],
                             update=False) if len(df) else 0
        nflag = int(df.side.notna().sum()) if len(df) else 0
        run.detail = {"season": season, "week": wk, "rows": run.rows, "flags": nflag, "tr": "unavailable" if tr is None else f"{n_mismatch} mismatches"}
        print(f"[l3] {season} wk{wk}: {run.rows} rows, {nflag} flags")
        return run.rows


# ------------------------------------------------------------------ grade
def grade_l3_experiment() -> int:
    flags = db.read_sql("""SELECT f.* FROM experimental_l3_flags f LEFT JOIN experimental_l3_grades g ON g.flag_id=f.id
                           LEFT JOIN experimental_l3_voids v ON v.flag_id=f.id
                           WHERE g.id IS NULL AND v.id IS NULL AND f.side IS NOT NULL AND f.kickoff_utc < now() - interval '4 hours'""")
    if flags.empty:
        print("[l3-grade] nothing to grade"); return 0
    with db.JobRun("grade_l3_experiment") as run:
        rows = []
        for _, c in flags.iterrows():
            stat_col, usage_col = STAT_COLS[c.market]
            st = db.read_sql(f"""SELECT {stat_col} AS stat, {usage_col} AS usage FROM raw_weekly_stats
                                 WHERE player_id=:p AND season=:s AND week=:w AND season_type='REG'""",
                             {"p": c.player_id, "s": int(c.season), "w": int(c.week)})
            if st.empty:
                st = db.read_sql(f"""SELECT {stat_col} AS stat, {usage_col} AS usage FROM raw_boxscores_espn
                                     WHERE player_id=:p AND season=:s AND week=:w AND game_id=:g""",
                                 {"p": c.player_id, "s": int(c.season), "w": int(c.week), "g": c.game_id})
            if st.empty:
                continue
            actual = float(st.stat.iloc[0] or 0)
            usage = st.usage.iloc[0]
            if pd.isna(usage) or usage == 0:
                result, profit = "void", 0.0
            elif actual == float(c.line):
                result, profit = "push", 0.0
            else:
                won = actual > float(c.line) if c.side == "Over" else actual < float(c.line)
                result, profit = ("win", float(c.price_decimal) - 1) if won else ("loss", -1.0)
            # CLV: last pre-kick snapshot's mean no-vig P(side) at the same line across bettable books
            close = db.read_sql("""SELECT l.line, l.side, l.bookmaker, l.price_decimal, s.taken_at FROM odds_lines l
                                   JOIN odds_snapshots s ON s.id=l.snapshot_id JOIN odds_events e ON e.event_id=l.event_id
                                   WHERE e.game_id=:g AND l.market=:m AND l.player=:p AND s.taken_at < :k
                                   ORDER BY s.taken_at DESC LIMIT 60""",
                                {"g": c.game_id, "m": c.market, "p": c.player_name, "k": c.kickoff_utc})
            clv, closing_line = None, None
            if len(close):
                close = close[close.bookmaker.map(is_bettable) & (close.taken_at == close.taken_at.max())]
                cl = consensus_live(close.assign(player=c.player_name, player_id=c.player_id, game_id=c.game_id,
                                                 price_american=0))
                if len(cl):
                    closing_line = float(cl.line.iloc[0])
                    fair = cl.fair_over.iloc[0] if c.side == "Over" else 1 - cl.fair_over.iloc[0]
                    shift = (closing_line - float(c.line)) * (-1 if c.side == "Over" else 1)
                    clv = float(fair - float(c.market_prob)) + 0.0035 * shift
            rows.append({"flag_id": int(c.id), "actual": actual, "result": result, "profit_units": profit,
                         "closing_line": closing_line, "clv_prob": clv})
        run.rows = db.append(pd.DataFrame(rows), "experimental_l3_grades") if rows else 0
        print(f"[l3-grade] graded {run.rows} flags")
        return run.rows
