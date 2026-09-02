"""Grade published (and unpublished) cards after games finalize. Append-only into `grades`.

Result uses the actual stat from raw_weekly_stats at the card's line/price. CLV: compare the
card's market_prob with the last snapshot's no-vig prob for the same side/line (if any).
"""
from __future__ import annotations
import pandas as pd
from .. import db


def grade_cards() -> int:
    cards = db.read_sql("""SELECT c.* FROM cards c LEFT JOIN grades g ON g.card_id=c.id
                           WHERE g.id IS NULL AND c.kickoff_utc < now() - interval '4 hours'""")
    if cards.empty:
        print("[grade] nothing to grade"); return 0
    with db.JobRun("grade") as run:
        rows = []
        for _, c in cards.iterrows():
            stat = db.read_sql("""SELECT passing_yards, attempts FROM raw_weekly_stats
                                  WHERE player_id=:p AND season=:s AND week=:w AND season_type='REG'""",
                               {"p": c.player_id, "s": int(c.season), "w": int(c.week)})
            if stat.empty:
                continue  # stats not published yet
            actual = float(stat.passing_yards.iloc[0] or 0)
            if pd.isna(stat.attempts.iloc[0]) or stat.attempts.iloc[0] == 0:
                result, profit = "void", 0.0
            elif actual == c.line:
                result, profit = "push", 0.0
            else:
                won = (actual > c.line) if c.side == "Over" else (actual < c.line)
                result = "win" if won else "loss"
                profit = float(c.price_decimal) - 1 if won else -1.0
            # closing line: last snapshot before kickoff for this player/market
            close = db.read_sql("""SELECT l.line, l.price_decimal, l.side, l.bookmaker FROM odds_lines l
                                   JOIN odds_snapshots s ON s.id=l.snapshot_id
                                   WHERE l.event_id=:e AND l.market=:m AND l.player=:p AND s.taken_at < :k
                                   ORDER BY s.taken_at DESC LIMIT 40""",
                               {"e": c.event_id, "m": c.market, "p": c.player_name, "k": c.kickoff_utc})
            clv, closing_line, closing_price = None, None, None
            if len(close):
                same = close[(close.bookmaker == c.book)]
                pair = same if len(same) >= 2 else close
                o = pair[pair.side == "Over"]; u = pair[pair.side == "Under"]
                if len(o) and len(u):
                    po, pu = 1 / o.price_decimal.iloc[0], 1 / u.price_decimal.iloc[0]
                    fair = (po if c.side == "Over" else pu) / (po + pu)
                    closing_line = float(o.line.iloc[0])
                    # CLV in probability space, adjusted for line change via the sign convention
                    line_shift = (closing_line - float(c.line)) * (-1 if c.side == "Over" else 1)
                    clv = float(fair - c.market_prob) + 0.0035 * line_shift   # ~0.35% per yard heuristic
                    closing_price = int((o if c.side == "Over" else u).price_decimal.iloc[0] * 0)  # placeholder
            rows.append({"card_id": int(c.id), "actual": actual, "result": result, "profit_units": profit,
                         "closing_line": closing_line, "closing_price_american": None, "clv_prob": clv})
        run.rows = db.append(pd.DataFrame(rows), "grades") if rows else 0
        print(f"[grade] graded {run.rows} cards")
        return run.rows
