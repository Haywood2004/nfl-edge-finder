"""Pre-game line watcher. Polls per-event prop markets at an adaptive cadence (docs/LIVE.md), prices every line
against the projection, and alerts when a candidate clears the publish bar.

Cadence per (event, market):
  cold  — no candidate within NEAR_BAR_MARGIN of the bar at the last poll: every SWEEP_MIN (default 6h)
  hot   — a candidate near/over the bar: every HOT_MIN (15 min); PREKICK_HOT_MIN (5 min) inside PREKICK_WINDOW_MIN
  every poll is gated by the credit Budget (monthly allowance, plan stop, hourly pacing)
"""
from __future__ import annotations
import datetime as dt
import time
import pandas as pd
from nfl_edge import db
from . import config as C
from .alerts import Alerter
from .odds import LiveOddsAPI, Budget, LineStore, refresh_events
from .pricing import WeekContext


class Watcher:
    def __init__(self, ctx: WeekContext | None = None, api: LiveOddsAPI | None = None, alerter: Alerter | None = None,
                 markets: tuple[str, ...] = C.PREGAME_MARKETS):
        self.ctx = ctx or WeekContext()
        self.api = api or LiveOddsAPI()
        self.alerter = alerter or Alerter()
        self.budget = Budget()
        self.store = LineStore()
        self.markets = tuple(m for m in markets if m in self.ctx.models)
        self.last_poll: dict[tuple[str, str], float] = {}     # (event_id, market) → epoch
        self.hot: dict[tuple[str, str], bool] = {}
        self.events = pd.DataFrame()
        self.events_at = 0.0
        self._restore_state()

    def _restore_state(self):
        """After a restart, last poll times come from live_snapshots so we do not immediately re-sweep everything."""
        r = db.read_sql("""SELECT event_id, unnest(markets) AS market, max(taken_at) AS t FROM live_snapshots
                           WHERE kind='pregame' AND taken_at > now() - interval '7 days' GROUP BY 1, 2""")
        for x in r.itertuples():
            self.last_poll[(x.event_id, x.market)] = pd.Timestamp(x.t).timestamp()

    # ---------------------------------------------------------------- schedule
    def refresh_events(self, force: bool = False):
        if not force and time.time() - self.events_at < 1800:
            return
        try:
            ev = refresh_events(self.api)
        except Exception as e:
            print(f"[pregame] events refresh failed: {e}")
            return
        wk = self.ctx.games.game_id.tolist()
        self.events = ev[ev.game_id.isin(wk)].copy()
        self.ctx.events.update(dict(zip(self.events.event_id, self.events.game_id)))
        self.events_at = time.time()

    def interval_min(self, key: tuple[str, str], mins_to_kick: float) -> float:
        hot = self.hot.get(key, True)      # unknown → treat as hot once so we discover the board quickly
        if mins_to_kick <= C.PREKICK_WINDOW_MIN:
            return C.PREKICK_HOT_MIN if hot else C.PREKICK_COLD_MIN
        return C.HOT_MIN if hot else C.SWEEP_MIN

    def due(self, now: dt.datetime | None = None) -> list[tuple[float, str, str, float]]:
        """(priority, event_id, market, minutes_to_kick) for event-markets whose interval has elapsed, most urgent first."""
        now = now or dt.datetime.now(dt.timezone.utc)
        out = []
        for e in self.events.itertuples():
            mins = (pd.Timestamp(e.commence_time) - pd.Timestamp(now)).total_seconds() / 60
            if mins <= 0:
                continue      # kicked off → the in-game module's problem
            for m in self.markets:
                key = (e.event_id, m)
                elapsed = (time.time() - self.last_poll.get(key, 0)) / 60
                iv = self.interval_min(key, mins)
                if elapsed >= iv:
                    urgency = elapsed / iv + (2.0 if self.hot.get(key, False) else 0.0) + (3.0 if mins <= C.PREKICK_WINDOW_MIN else 0.0)
                    out.append((urgency, e.event_id, m, mins))
        return sorted(out, reverse=True)

    # ---------------------------------------------------------------- one poll
    def poll(self, event_id: str, market: str, mins_to_kick: float | None = None) -> int:
        ok, why = self.budget.can_spend(1)
        if not ok:
            print(f"[pregame] skip {event_id[:8]} {market}: {why}")
            return 0
        try:
            payload = self.api.event_odds(event_id, (market,))
        except Exception as e:
            print(f"[pregame] odds call failed {event_id[:8]} {market}: {e}")
            self.last_poll[(event_id, market)] = time.time() - 60 * (C.HOT_MIN - 2)   # retry in ~2 min, not immediately
            return 0
        cost = self.api.last_cost()
        self.budget.record(cost, self.api.remaining())
        self.last_poll[(event_id, market)] = time.time()
        game_id = self.ctx.events.get(event_id)
        snap_id, live_id, seen = self.store.store("pregame", event_id, game_id, (market,), payload, cost,
                                                  self.ctx.season, self.ctx.week, detail={"minutes_to_kick": mins_to_kick})
        lines = seen[seen.market == market] if len(seen) else seen
        cands = self.ctx.price(market, event_id, lines) if len(lines) else []
        self.hot[(event_id, market)] = any(c.near_bar for c in cands)
        n = 0
        for c in cands:
            if c.clears_bar:
                self.alerter.alert(c, self.ctx, snap_id, live_id, kind="pregame")
                n += 1
        best = max((c.edge for c in cands), default=None)
        best_txt = f"best edge {best:+.1%}" if best is not None else "nothing priced"
        print(f"[pregame] {event_id[:8]} {market}: {len(lines)} lines, {len(cands)} priced, {best_txt} | {n} alert(s) | {self.budget.summary()}")
        return n

    # ---------------------------------------------------------------- loop
    def tick(self, max_polls: int = 8) -> int:
        self.ctx.refresh()
        self.budget.refresh()
        self.refresh_events()
        n = 0
        for _, eid, m, mins in self.due()[:max_polls]:
            n += self.poll(eid, m, mins)
        self.alerter.flush()
        return n

    def run(self, once: bool = False):
        print(f"[pregame] watching {len(self.markets)} markets: {self.markets}; {self.budget.summary()}; paper_only={C.PAPER_ONLY} dry_run={C.DRY_RUN}")
        while True:
            try:
                self.tick()
            except Exception as e:      # never die on one bad cycle; graceful degradation
                print(f"[pregame] tick failed: {e!r}")
            if once:
                self.alerter.flush(force=True)
                return
            time.sleep(C.LOOP_SLEEP_SEC)
