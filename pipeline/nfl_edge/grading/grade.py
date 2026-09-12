"""Grade every ungraded card after its game finalizes. Append-only into `grades`.

Props: the actual stat for the card's market from raw_weekly_stats, at the card's line/price. A bet is VOID when the
player recorded no usage in that market (0 attempts / targets / carries) — the same rule the closing-line backtest
uses, because books void props for players who didn't play. Moneylines: the final score from raw_games.
CLV: the card's market_prob vs the last pre-kick snapshot's no-vig prob for the same side (props only).
"""
from __future__ import annotations
import pandas as pd
from .. import db

# market → (stat column, usage column) in raw_weekly_stats
STAT_COLS = {
    "player_pass_yds": ("passing_yards", "attempts"),
    "player_reception_yds": ("receiving_yards", "targets"),
    "player_receptions": ("receptions", "targets"),
    "player_rush_yds": ("rushing_yards", "carries"),
}


def _grade_prop(c) -> tuple[float, str, float] | None:
    stat_col, usage_col = STAT_COLS[c.market]
    stat = db.read_sql(f"""SELECT {stat_col} AS stat, {usage_col} AS usage FROM raw_weekly_stats
                           WHERE player_id=:p AND season=:s AND week=:w AND season_type='REG'""",
                       {"p": c.player_id, "s": int(c.season), "w": int(c.week)})
    if stat.empty:   # nflverse weekly stats not published yet → same-day ESPN box score (ingest/espn_boxscores.py)
        stat = db.read_sql(f"""SELECT {stat_col} AS stat, {usage_col} AS usage FROM raw_boxscores_espn
                               WHERE player_id=:p AND season=:s AND week=:w AND game_id=:g""",
                           {"p": c.player_id, "s": int(c.season), "w": int(c.week), "g": c.game_id})
    if stat.empty:
        return None  # no stats yet
    actual = float(stat.stat.iloc[0] or 0)
    usage = stat.usage.iloc[0]
    if pd.isna(usage) or usage == 0:
        return actual, "void", 0.0
    if actual == float(c.line):
        return actual, "push", 0.0
    won = (actual > float(c.line)) if c.side == "Over" else (actual < float(c.line))
    return actual, ("win" if won else "loss"), (float(c.price_decimal) - 1 if won else -1.0)


def _grade_moneyline(c) -> tuple[float, str, float] | None:
    g = db.read_sql("SELECT home_team, away_team, home_score, away_score FROM raw_games WHERE game_id=:g", {"g": c.game_id})
    if g.empty or pd.isna(g.home_score.iloc[0]) or pd.isna(g.away_score.iloc[0]):
        return None
    hs, as_ = int(g.home_score.iloc[0]), int(g.away_score.iloc[0])
    mine = hs if c.team == g.home_team.iloc[0] else as_
    theirs = as_ if c.team == g.home_team.iloc[0] else hs
    margin = float(mine - theirs)
    if margin == 0:
        return margin, "push", 0.0
    won = margin > 0
    return margin, ("win" if won else "loss"), (float(c.price_decimal) - 1 if won else -1.0)


def _grade_spread(c) -> tuple[float, str, float] | None:
    """Spread card: side = team abbr, line = that team's handicap. Covers when margin + line > 0."""
    g = db.read_sql("SELECT home_team, away_team, home_score, away_score FROM raw_games WHERE game_id=:g", {"g": c.game_id})
    if g.empty or pd.isna(g.home_score.iloc[0]) or pd.isna(g.away_score.iloc[0]):
        return None
    hs, as_ = int(g.home_score.iloc[0]), int(g.away_score.iloc[0])
    margin = float(hs - as_) if c.team == g.home_team.iloc[0] else float(as_ - hs)
    adj = margin + float(c.line)
    if adj == 0:
        return margin, "push", 0.0
    won = adj > 0
    return margin, ("win" if won else "loss"), (float(c.price_decimal) - 1 if won else -1.0)


def grade_cards() -> int:
    cards = db.read_sql("""SELECT c.* FROM cards c LEFT JOIN grades g ON g.card_id=c.id
                           WHERE g.id IS NULL AND c.kickoff_utc < now() - interval '4 hours'""")
    if cards.empty:
        print("[grade] nothing to grade"); return 0
    with db.JobRun("grade") as run:
        rows = []
        skipped = {}
        for _, c in cards.iterrows():
            if c.market in STAT_COLS:
                res = _grade_prop(c)
            elif c.market == "h2h":
                res = _grade_moneyline(c)
            elif c.market == "spreads":
                res = _grade_spread(c)
            else:
                skipped[c.market] = skipped.get(c.market, 0) + 1
                continue
            if res is None:
                continue
            actual, result, profit = res
            clv, closing_line = None, None
            if c.market in STAT_COLS:
                # closing line: last pipeline snapshot before kickoff for this player/market (live polls never write odds_lines)
                close = db.read_sql("""SELECT l.line, l.price_decimal, l.side, l.bookmaker FROM odds_lines l
                                       JOIN odds_snapshots s ON s.id=l.snapshot_id
                                       WHERE l.event_id=:e AND l.market=:m AND l.player=:p AND s.taken_at < :k
                                       ORDER BY s.taken_at DESC LIMIT 40""",
                                   {"e": c.event_id, "m": c.market, "p": c.player_name, "k": c.kickoff_utc})
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
                        per_unit = 0.03 if c.market == "player_receptions" else 0.0035   # ~0.35%/yd, ~3%/reception heuristic
                        clv = float(fair - c.market_prob) + per_unit * line_shift
            rows.append({"card_id": int(c.id), "actual": actual, "result": result, "profit_units": profit,
                         "closing_line": closing_line, "closing_price_american": None, "clv_prob": clv})
        run.rows = db.append(pd.DataFrame(rows), "grades") if rows else 0
        if skipped:
            print(f"[grade] skipped unknown markets: {skipped}")
        print(f"[grade] graded {run.rows} cards")
        return run.rows
