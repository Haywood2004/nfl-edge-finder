"""The Odds API for the live bot: same client as the pipeline (credit accounting into `api_usage`, notes prefixed
`live:` so spend is separable), a budget guard, and append-only storage of polls into live_snapshots / live_lines.

Storage rule (docs/LIVE.md): every poll writes one odds_snapshots row (label 'live_pregame'|'live_ingame', markets
prefixed 'live:' so the pipeline's "latest snapshot for market X" queries never pick a live poll) plus one
live_snapshots row; lines are stored in live_lines only when they differ from the last stored line for the same
(event, market, book, player, side). Unchanged lines are counted (n_lines) but not re-stored.
"""
from __future__ import annotations
import datetime as dt
import pandas as pd
from nfl_edge import db
from nfl_edge.sources.odds_api import OddsAPI, american
from nfl_edge.ingest.odds_jobs import _lines_from_bookmakers, _map_events
from . import config as C


class LiveOddsAPI(OddsAPI):
    """Every call is logged to api_usage with note 'live:<what>'."""

    def events(self) -> list[dict]:
        return self._get(f"/sports/americanfootball_nfl/events", {}, "live:events")

    def event_odds(self, event_id: str, markets: tuple[str, ...], regions: str = "us") -> dict:
        return self._get(f"/sports/americanfootball_nfl/events/{event_id}/odds",
                         {"markets": ",".join(markets), "regions": regions, "oddsFormat": "decimal"},
                         f"live:event_odds:{event_id}")

    def last_cost(self) -> int:
        return int(self.last_headers.get("x-requests-last", 0) or 0)

    def remaining(self) -> int | None:
        r = self.last_headers.get("x-requests-remaining")
        return int(r) if r is not None else None


class Budget:
    """Credit guard. Two limits: the bot's own monthly allowance (LIVE_CREDIT_BUDGET) and the whole key's plan
    (stop when used ≥ STOP_AT_FRACTION × ODDS_MONTHLY_CREDITS, read from the API's x-requests-remaining header).
    Pacing: spend evenly through the month, with a burst allowance, so a hot Tuesday cannot eat the Sunday slate."""

    def __init__(self):
        self.refresh()

    def refresh(self):
        now = dt.datetime.now(dt.timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        r = db.read_sql("""SELECT coalesce(sum(credits_used), 0) AS live_spent,
                                  coalesce(sum(credits_used) FILTER (WHERE ts > now() - interval '1 hour'), 0) AS live_last_hour
                           FROM api_usage WHERE ts >= :m AND note LIKE 'live:%%'""", {"m": month_start})
        self.live_spent = int(r.live_spent.iloc[0]); self.live_last_hour = int(r.live_last_hour.iloc[0])
        k = db.read_sql("SELECT credits_remaining FROM api_usage WHERE credits_remaining IS NOT NULL ORDER BY ts DESC LIMIT 1")
        self.key_remaining = int(k.credits_remaining.iloc[0]) if len(k) else None
        nxt = (month_start + dt.timedelta(days=32)).replace(day=1)
        self.hours_left = max((nxt - now).total_seconds() / 3600, 1.0)
        self.live_remaining = max(C.LIVE_CREDIT_BUDGET - self.live_spent, 0)
        self.hourly_allowance = self.live_remaining / self.hours_left

    def can_spend(self, credits: int) -> tuple[bool, str]:
        if self.key_remaining is not None and self.key_remaining - credits < C.ODDS_MONTHLY * (1 - C.STOP_AT_FRACTION):
            return False, f"key at {C.STOP_AT_FRACTION:.0%} of plan ({self.key_remaining} left)"
        if self.live_spent + credits > C.LIVE_CREDIT_BUDGET:
            return False, f"live budget {C.LIVE_CREDIT_BUDGET} exhausted ({self.live_spent} spent)"
        if self.live_last_hour + credits > self.hourly_allowance * C.PACING_BURST + 1:
            return False, f"pacing: {self.live_last_hour} spent this hour, allowance {self.hourly_allowance:.1f}/h × burst {C.PACING_BURST}"
        return True, ""

    def record(self, credits: int, remaining: int | None):
        self.live_spent += credits; self.live_last_hour += credits
        if remaining is not None:
            self.key_remaining = remaining

    def summary(self) -> str:
        return (f"live {self.live_spent}/{C.LIVE_CREDIT_BUDGET} this month ({self.live_last_hour} last hour, allowance {self.hourly_allowance:.1f}/h), "
                f"key remaining {self.key_remaining}")


class LineStore:
    """Diff-store of polled lines. Warm-started from live_lines so restarts do not re-store the whole board."""

    def __init__(self):
        self.last: dict[tuple, tuple[float | None, float]] = {}
        r = db.read_sql("""SELECT DISTINCT ON (event_id, market, bookmaker, player, side) event_id, market, bookmaker, player, side, line, price_decimal
                           FROM live_lines WHERE seen_at > now() - interval '10 days'
                           ORDER BY event_id, market, bookmaker, player, side, seen_at DESC""")
        for x in r.itertuples():
            self.last[(x.event_id, x.market, x.bookmaker, x.player, x.side)] = (None if pd.isna(x.line) else float(x.line), float(x.price_decimal))

    def store(self, kind: str, event_id: str | None, game_id: str | None, markets: tuple[str, ...], payload: dict | list,
              credits: int, season: int, week: int, is_live: bool = False, game_state_id: int | None = None,
              detail: dict | None = None) -> tuple[int, int, pd.DataFrame]:
        """Returns (odds_snapshot_id, live_snapshot_id, all lines seen as a DataFrame)."""
        snap_id = db.insert_returning_id("odds_snapshots", {
            "label": f"live_{kind}", "season": season, "week": week, "markets": [f"live:{m}" for m in markets],
            "credits_used": credits, "source": "api"})
        if isinstance(payload, dict):
            rows = _lines_from_bookmakers(payload.get("id", event_id), payload.get("bookmakers", []), snap_id)
        else:
            rows = []
            for e in payload:
                rows += _lines_from_bookmakers(e["id"], e.get("bookmakers", []), snap_id)
        seen = pd.DataFrame(rows)
        new = []
        for r in rows:
            key = (r["event_id"], r["market"], r["bookmaker"], r["player"], r["side"])
            val = (None if r["line"] is None else float(r["line"]), float(r["price_decimal"]))
            if self.last.get(key) != val:
                self.last[key] = val
                new.append(r)
        live_id = db.insert_returning_id("live_snapshots", {
            "snapshot_id": snap_id, "kind": kind, "event_id": event_id, "game_id": game_id, "markets": list(markets),
            "credits_used": credits, "n_lines": len(rows), "n_new": len(new), "game_state_id": game_state_id, "detail": detail or {}})
        if new:
            df = pd.DataFrame(new).drop(columns=["snapshot_id", "book_title"])
            df["live_snapshot_id"] = live_id
            df["is_live"] = is_live
            db.append(df, "live_lines")
        return snap_id, live_id, seen


def refresh_events(api: LiveOddsAPI) -> pd.DataFrame:
    """Events list is free (0 credits). Mapped to raw_games the way the pipeline does, but kept in memory:
    odds_events is the pipeline's table and the live bot does not write outside live_* / cards(source='live')."""
    return _map_events(api.events())
