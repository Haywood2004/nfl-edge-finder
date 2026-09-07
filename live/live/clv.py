"""Closing-line value for live alerts — the primary success metric (docs/AGENT_LIVE_BOT.md).

Pre-game alerts: horizon 'close' = the last line seen before kickoff for the same book/player/market (from live_lines,
falling back to the pipeline's odds_lines). In-game alerts: '30s' and 'dead_ball' are measured by the tracker.
clv_prob = fair(no-vig) prob of our side at the horizon − fair prob at alert time (positive = market moved toward us).
clv_line = line at horizon − line at alert, signed toward us (Over: alert line − close line; Under: close − alert).
"""
from __future__ import annotations
import pandas as pd
from nfl_edge import db
from .pricing import norm_name


def _fair_for_side(pair: pd.DataFrame, side: str) -> tuple[float, float, float] | None:
    o = pair[pair.side == "Over"]; u = pair[pair.side == "Under"]
    if o.empty or u.empty:
        return None
    po, pu = 1 / float(o.price_decimal.iloc[0]), 1 / float(u.price_decimal.iloc[0])
    fair = (po if side == "Over" else pu) / (po + pu)
    dec = float((o if side == "Over" else u).price_decimal.iloc[0])
    return fair, float(o.line.iloc[0]), dec


def measure_from_lines(alert_id: int, horizon: str, lines: pd.DataFrame, player: str, book: str, side: str, line: float,
                       market_prob: float, source: str = "live_lines") -> dict | None:
    """Pick the same book's two-way line for the player (any line: line change is captured in clv_line)."""
    if lines is None or lines.empty:
        return None
    l = lines[lines.player.map(norm_name) == norm_name(player)]
    same = l[l.bookmaker == book]
    if same.empty:
        same = l                       # book pulled the market: use the consensus of what is left
    if same.empty:
        return None
    # main line = the one closest to even money at that book
    best = None
    for ln, g in same.groupby("line"):
        r = _fair_for_side(g, side)
        if r and (best is None or abs(r[0] - 0.5) < abs(best[0] - 0.5)):
            best = r
    if best is None:
        return None
    fair, close_line, dec = best
    clv_line = (line - close_line) if side == "Over" else (close_line - line)
    row = {"alert_id": alert_id, "horizon": horizon, "bookmaker": book if not same.empty else None, "line": close_line, "price_decimal": dec,
           "market_prob": fair, "clv_prob": fair - market_prob, "clv_line": clv_line, "source": source}
    db.execute("""INSERT INTO live_clv (alert_id, horizon, bookmaker, line, price_decimal, market_prob, clv_prob, clv_line, source)
                  VALUES (:alert_id, :horizon, :bookmaker, :line, :price_decimal, :market_prob, :clv_prob, :clv_line, :source)
                  ON CONFLICT (alert_id, horizon) DO NOTHING""", row)
    return row


def close_pregame_alerts() -> int:
    """For every pre-game alert whose game has kicked off and has no 'close' row yet, find the closing line."""
    a = db.read_sql("""SELECT a.id, a.payload, c.kickoff_utc, c.event_id, c.market, c.player_name, c.book, c.side, c.line, c.market_prob
                       FROM live_alerts a JOIN cards c ON c.id = a.card_id
                       LEFT JOIN live_clv v ON v.alert_id = a.id AND v.horizon = 'close'
                       WHERE a.kind='pregame' AND a.card_id IS NOT NULL AND v.id IS NULL AND c.kickoff_utc < now()""")
    n = 0
    for x in a.itertuples():
        # last live poll before kickoff for this event/market
        ll = db.read_sql("""SELECT l.bookmaker, l.player, l.side, l.line, l.price_decimal FROM live_lines l
                            WHERE l.event_id=:e AND l.market=:m AND l.seen_at < :k AND l.player IS NOT NULL
                              AND l.seen_at = (SELECT max(seen_at) FROM live_lines WHERE event_id=:e AND market=:m AND bookmaker=l.bookmaker
                                                AND player=l.player AND side=l.side AND seen_at < :k)""",
                         {"e": x.event_id, "m": x.market, "k": x.kickoff_utc})
        src = "live_lines"
        if ll.empty or ll[ll.player.map(norm_name) == norm_name(x.player_name)].empty:
            ll = db.read_sql("""SELECT l.bookmaker, l.player, l.side, l.line, l.price_decimal FROM odds_lines l JOIN odds_snapshots s ON s.id=l.snapshot_id
                                WHERE l.event_id=:e AND l.market=:m AND l.player=:p AND s.taken_at < :k
                                  AND s.id = (SELECT max(s2.id) FROM odds_snapshots s2 JOIN odds_lines l2 ON l2.snapshot_id=s2.id
                                              WHERE l2.event_id=:e AND l2.market=:m AND l2.player=:p AND s2.taken_at < :k)""",
                             {"e": x.event_id, "m": x.market, "p": x.player_name, "k": x.kickoff_utc})
            src = "odds_lines"
        r = measure_from_lines(int(x.id), "close", ll, x.player_name, x.book, x.side, float(x.line), float(x.market_prob), source=src)
        if r:
            n += 1
    print(f"[clv] closed {n} pre-game alert(s)")
    return n


def report(days: int = 7) -> pd.DataFrame:
    """Weekly numbers for docs/TODO.md: alerts, hit rate (market-aware, straight from raw_weekly_stats), CLV, credits."""
    a = db.read_sql("""SELECT a.id, a.kind, a.status, a.created_at, c.season, c.week, c.market, c.side, c.line, c.price_decimal, c.player_id,
                              c.edge, c.confidence, v.clv_prob, v.clv_line
                       FROM live_alerts a LEFT JOIN cards c ON c.id = a.card_id
                       LEFT JOIN live_clv v ON v.alert_id = a.id AND v.horizon = 'close'
                       WHERE a.created_at > now() - make_interval(days => :d)""", {"d": days})
    if a.empty:
        print("[report] no alerts in window"); return a
    stat_col = {"player_pass_yds": "passing_yards", "player_reception_yds": "receiving_yards", "player_receptions": "receptions", "player_rush_yds": "rushing_yards"}
    res = []
    for x in a.itertuples():
        if pd.isna(x.player_id):
            res.append(None); continue
        s = db.read_sql(f"SELECT {stat_col.get(x.market, 'passing_yards')} AS v FROM raw_weekly_stats WHERE player_id=:p AND season=:s AND week=:w AND season_type='REG'",
                        {"p": x.player_id, "s": int(x.season), "w": int(x.week)})
        if s.empty or pd.isna(s.v.iloc[0]):
            res.append(None); continue
        v = float(s.v.iloc[0]); ln = float(x.line)
        res.append("push" if v == ln else ("win" if ((v > ln) if x.side == "Over" else (v < ln)) else "loss"))
    a["result"] = res
    a["profit"] = [(float(p) - 1 if r == "win" else (-1.0 if r == "loss" else 0.0)) if r else None for r, p in zip(a.result, a.price_decimal.fillna(1))]
    cr = db.read_sql("SELECT coalesce(sum(credits_used),0) AS c FROM api_usage WHERE note LIKE 'live:%%' AND ts > now() - make_interval(days => :d)", {"d": days})
    g = a[a.card_id.notna()] if "card_id" in a else a
    summary = {
        "alerts_total": int(len(a)), "sent": int((a.status == "sent").sum()), "not_sent": int((a.status == "not_sent").sum()),
        "suppressed": int((a.status == "suppressed").sum()), "graded": int(a.result.notna().sum()),
        "wins": int((a.result == "win").sum()), "losses": int((a.result == "loss").sum()), "pushes": int((a.result == "push").sum()),
        "units": float(a.profit.dropna().sum()) if a.profit.notna().any() else 0.0,
        "clv_prob_mean": float(a.clv_prob.dropna().mean()) if a.clv_prob.notna().any() else None,
        "clv_positive_share": float((a.clv_prob.dropna() > 0).mean()) if a.clv_prob.notna().any() else None,
        "credits": int(cr.c.iloc[0]),
    }
    print("[report]", summary)
    return a
