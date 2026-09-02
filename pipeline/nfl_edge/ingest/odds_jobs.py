"""Odds snapshot ingest (append-only).

ingest_odds(label, prop_markets, week=None, from_dir=None)
  1. events → odds_events (mapped to raw_games.game_id by abbreviations + kickoff date)
  2. new odds_snapshots row
  3. game markets (h2h/spreads/totals) for all upcoming events → odds_lines
  4. per-event prop markets for the target week's events → odds_lines
  5. odds_consensus (best price per side, mean no-vig prob across books)

from_dir replays recorded payloads: <dir>/events.json, <dir>/game_odds.json, <dir>/event_odds/<event_id>.json
"""
from __future__ import annotations
import datetime as dt
import json
from pathlib import Path
import pandas as pd
from .. import db
from ..sources.odds_api import OddsAPI, load_payload, american, implied
from ..teams import ODDS_API_TO_ABBR
from .nflverse_jobs import current_season


def target_week(season: int | None = None, now: dt.datetime | None = None) -> tuple[int, int]:
    """The first regular-season week with a game that hasn't kicked off yet."""
    season = season or current_season()
    now = now or dt.datetime.now(dt.timezone.utc)
    r = db.read_sql("""SELECT week FROM raw_games WHERE season=:s AND game_type='REG' AND kickoff_utc > :now
                       ORDER BY week LIMIT 1""", {"s": season, "now": now})
    if r.empty:
        r = db.read_sql("SELECT max(week) AS week FROM raw_games WHERE season=:s AND game_type='REG'", {"s": season})
    return season, int(r.week.iloc[0])


def _map_events(events: list[dict]) -> pd.DataFrame:
    ev = pd.DataFrame(events)
    ev["home_abbr"] = ev.home_team.map(ODDS_API_TO_ABBR)
    ev["away_abbr"] = ev.away_team.map(ODDS_API_TO_ABBR)
    ev["commence_time"] = pd.to_datetime(ev.commence_time, utc=True)
    games = db.read_sql("SELECT game_id, home_team, away_team, kickoff_utc FROM raw_games WHERE season>=:s",
                        {"s": current_season() - 1})
    games["kickoff_utc"] = pd.to_datetime(games.kickoff_utc, utc=True)
    # match on teams and kickoff within 36h (books sometimes list TBD times)
    m = ev.merge(games, left_on=["home_abbr", "away_abbr"], right_on=["home_team", "away_team"],
                 how="left", suffixes=("", "_g"))
    m["dh"] = (m.commence_time - m.kickoff_utc).abs().dt.total_seconds() / 3600
    m = m[(m.dh <= 36) | m.game_id.isna()].sort_values("dh").drop_duplicates("id")
    out = ev.merge(m[["id", "game_id"]], on="id", how="left")
    return out.rename(columns={"id": "event_id"})[
        ["event_id", "game_id", "commence_time", "home_team", "away_team", "home_abbr", "away_abbr"]]


def _lines_from_bookmakers(event_id: str, bookmakers: list[dict], snapshot_id: int) -> list[dict]:
    rows = []
    for bk in bookmakers:
        for mk in bk.get("markets", []):
            for o in mk.get("outcomes", []):
                price = float(o["price"])
                rows.append({
                    "snapshot_id": snapshot_id, "event_id": event_id, "market": mk["key"],
                    "bookmaker": bk["key"], "book_title": bk.get("title"),
                    "player": o.get("description"), "side": o["name"], "line": o.get("point"),
                    "price_decimal": price, "price_american": american(price),
                    "book_last_update": mk.get("last_update"),
                })
    return rows


def build_consensus(snapshot_id: int) -> int:
    """Best price per side + mean no-vig probability across books for each line."""
    lines = db.read_sql("SELECT * FROM odds_lines WHERE snapshot_id=:s", {"s": snapshot_id})
    if lines.empty:
        return 0
    lines["player"] = lines.player.fillna("")
    lines["line"] = lines.line.astype(float)
    out = []
    key = ["event_id", "market", "player", "line"]
    for (event_id, market, player, line), g in lines.groupby(key, dropna=False):
        by_book = {}
        for _, r in g.iterrows():
            by_book.setdefault(r.bookmaker, {})[r.side] = r
        sides = sorted({s for d in by_book.values() for s in d})
        if len(sides) != 2:
            continue  # need a two-way market to de-vig
        a, b = sides  # e.g. Over/Under or Team A/Team B
        pa, pb = [], []
        best = {a: None, b: None}
        for book, d in by_book.items():
            if a in d and b in d:
                ia, ib = implied(d[a].price_decimal), implied(d[b].price_decimal)
                s = ia + ib
                pa.append(ia / s); pb.append(ib / s)
            for side in (a, b):
                if side in d and (best[side] is None or d[side].price_decimal > best[side].price_decimal):
                    best[side] = d[side]
        if not pa:
            continue
        # column naming: "over" = first side alphabetically for team markets; Over/Under for props/totals
        oa, ob = (a, b) if a == "Over" else ((b, a) if b == "Over" else (a, b))
        best_o, best_u = best[oa], best[ob]
        po = sum(pa) / len(pa) if oa == a else sum(pb) / len(pb)
        pu = 1 - po
        out.append({
            "snapshot_id": snapshot_id, "event_id": event_id, "market": market,
            "player": player or None, "player_id": None, "line": None if pd.isna(line) else line,
            "n_books": len(pa),
            "over_best_price": best_o.price_decimal, "over_best_book": best_o.bookmaker,
            "over_best_american": int(best_o.price_american),
            "under_best_price": best_u.price_decimal, "under_best_book": best_u.bookmaker,
            "under_best_american": int(best_u.price_american),
            "over_consensus_prob": po, "under_consensus_prob": pu,
        })
    df = pd.DataFrame(out)
    return db.upsert(df, "odds_consensus", ["snapshot_id", "event_id", "market", "player", "line"])


def ingest_odds(label: str = "manual", prop_markets: tuple[str, ...] = ("player_pass_yds",),
                game_markets: tuple[str, ...] = ("h2h", "spreads", "totals"),
                week: int | None = None, from_dir: str | Path | None = None,
                max_events: int | None = None) -> int:
    season, wk = target_week()
    if week:
        wk = week
    api = None if from_dir else OddsAPI()
    from_dir = Path(from_dir) if from_dir else None

    with db.JobRun(f"ingest_odds:{label}") as run:
        events = load_payload(from_dir / "events.json") if from_dir else api.events()
        ev = _map_events(events)
        db.upsert(ev, "odds_events", ["event_id"])

        snap_id = db.insert_returning_id("odds_snapshots", {
            "label": label, "season": season, "week": wk,
            "markets": list(game_markets) + list(prop_markets), "source": "file" if from_dir else "api",
        })
        rows: list[dict] = []
        credits = 0

        # game markets: one call covers every listed event
        if game_markets:
            if from_dir:
                p = from_dir / "game_odds.json"
                go = load_payload(p) if p.exists() else []
            else:
                go = api.game_odds(game_markets)
                credits += int(api.last_headers.get("x-requests-last", 0) or 0)
            for e in go:
                rows += _lines_from_bookmakers(e["id"], e.get("bookmakers", []), snap_id)

        # props: per event for this week's games only
        wk_games = db.read_sql("SELECT game_id FROM raw_games WHERE season=:s AND week=:w AND game_type='REG'",
                               {"s": season, "w": wk}).game_id.tolist()
        targets = ev[ev.game_id.isin(wk_games)]
        if max_events:
            targets = targets.head(max_events)
        missing = []
        for eid in targets.event_id:
            if from_dir:
                p = from_dir / "event_odds" / f"{eid}.json"
                if not p.exists():
                    missing.append(eid); continue
                eo = load_payload(p)
            else:
                eo = api.event_odds(eid, prop_markets)
                credits += int(api.last_headers.get("x-requests-last", 0) or 0)
            rows += _lines_from_bookmakers(eid, eo.get("bookmakers", []), snap_id)

        n = db.append(pd.DataFrame(rows), "odds_lines") if rows else 0
        db.execute("UPDATE odds_snapshots SET credits_used=:c WHERE id=:id", {"c": credits, "id": snap_id})
        nc = build_consensus(snap_id)
        run.rows = n
        run.detail = {"snapshot_id": snap_id, "season": season, "week": wk, "consensus_rows": nc,
                      "credits": credits, "events_missing_props": missing}
        print(f"[odds] snapshot {snap_id} ({label}) wk{wk}: {n} lines, {nc} consensus rows, {credits} credits"
              + (f", {len(missing)} events without prop payloads" if missing else ""))
        return snap_id
