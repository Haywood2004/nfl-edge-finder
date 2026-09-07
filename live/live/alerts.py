"""Alert delivery + logging. Every alert that clears the bar becomes a `cards` row (source='live', published=false
during the paper period) and a `live_alerts` row, whether or not the message went out. Messages are batched
within ALERT_BATCH_SECONDS and rate-limited; anything that could not be sent is logged status='not_sent'.

Card anatomy mirrors the site: bet, price, book, model %, market %, edge, calibrated edge, stake, bottom line, link.
"""
from __future__ import annotations
import datetime as dt
import json
import time
import requests
from nfl_edge import db
from . import config as C
from .kelly import kelly_stake
from .pricing import Candidate, bar_for

UA = {"User-Agent": "nfl-edge-live/0.1"}


def fmt_american(a: int) -> str:
    return f"+{a}" if a > 0 else str(a)


def stake_for(c: Candidate) -> float:
    p = c.prob_calibrated if c.prob_calibrated is not None else c.model_prob
    return kelly_stake(p, c.price_decimal)


def render(c: Candidate, card_id: int | None, kind: str, extra: str = "") -> dict:
    """One Discord embed for a candidate (also the text body for Telegram)."""
    mins = (c.kickoff_utc - dt.datetime.now(dt.timezone.utc)).total_seconds() / 60
    when = f"kicks in {mins / 60:.1f}h" if kind == "pregame" else f"LIVE {extra}".strip()
    market_lbl = {"player_pass_yds": "Passing Yards", "player_reception_yds": "Receiving Yards", "player_receptions": "Receptions",
                  "player_rush_yds": "Rushing Yards"}.get(c.market, c.market)
    cal = f"{c.edge_calibrated:+.1%}" if c.edge_calibrated is not None else "n/a"
    stake = stake_for(c)
    bottom = next((f["text"] for f in c.factors if f["factor"] == "bottom_line"), "")
    others = [f"{f.get('impact', '▬')} {f['text']}" for f in c.factors if f["factor"] != "bottom_line"][:4]
    title = f"[{c.position or '?'}] {market_lbl} {c.side.upper()} {c.line:g}  ({fmt_american(c.price_american)} {c.book})"
    desc = (f"**{c.player_name}** · {c.team} vs {c.opponent} · {when}\n"
            f"Edge **{c.edge:+.1%}** · Model {c.model_prob:.0%} · Market {c.market_prob:.0%} · Conf {c.confidence}\n"
            f"Calibrated edge {cal} ({'pre-game calibrator; uncalibrated for live' if kind == 'ingame' else 'pre-game calibrator'}) · "
            f"Stake **{stake:.2f}u** (¼ Kelly)\n"
            f"Projection median {c.q50_live:.0f} (sd {c.sd:.0f}) · consensus {c.consensus_line:g}"
            + (f" · open {c.open_line:g}" if c.open_line is not None else "") + f" · {c.n_books} books\n\n"
            f"{bottom}\n" + "\n".join(others))
    if card_id:
        desc += f"\n\n[card #{card_id}]({C.CARD_URL_BASE}/cards/{card_id}) · paper alert, not a published pick"
    else:
        desc += "\n\npaper alert, not a published pick"
    color = 0x2ecc71 if c.side == "Over" else 0xe67e22
    return {"title": title[:256], "description": desc[:4000], "color": color,
            "footer": {"text": f"{'PAPER · ' if C.PAPER_ONLY else ''}live bot · {kind} · bar {bar_for(c.market):.0%}/conf {C.PUBLISH_MIN_CONFIDENCE} · informational, not financial advice · 1-800-GAMBLER"}}


class Alerter:
    """Collects alerts, flushes in batches, logs every decision."""

    def __init__(self):
        self.pending: list[tuple[int, dict]] = []      # (live_alert_id, embed)
        self.first_pending_at: float | None = None
        self.sent_times: list[float] = []
        self.recent: dict[str, tuple[float, float]] = {}   # dedupe_key → (last alert time, edge)
        r = db.read_sql("""SELECT DISTINCT ON (dedupe_key) dedupe_key, created_at, (payload->>'edge')::float AS edge
                           FROM live_alerts WHERE created_at > now() - interval '2 days' ORDER BY dedupe_key, created_at DESC""")
        for x in r.itertuples():
            self.recent[x.dedupe_key] = (x.created_at.timestamp(), float(x.edge) if x.edge is not None else 0.0)

    # ---------------------------------------------------------------- decisions
    def suppressed_reason(self, c: Candidate) -> str | None:
        prev = self.recent.get(c.dedupe_key)
        if prev is None:
            return None
        t, e = prev
        if time.time() - t < C.ALERT_COOLDOWN_HOURS * 3600 and c.edge < e + C.ALERT_REALERT_EDGE_GAIN:
            return "cooldown"
        return None

    def alert(self, c: Candidate, ctx, snapshot_id: int, live_snapshot_id: int, kind: str = "pregame",
              game_state_id: int | None = None, extra: str = "") -> int | None:
        """Log a card + alert row for a candidate that clears the bar; queue the message. Returns live_alerts.id."""
        reason = self.suppressed_reason(c)
        card_id = None
        if reason is None:
            card_id = db.insert_returning_id("cards", ctx.card_row(c, snapshot_id, published=False))
        mins = (c.kickoff_utc - dt.datetime.now(dt.timezone.utc)).total_seconds() / 60
        payload = {"player": c.player_name, "market": c.market, "side": c.side, "line": c.line, "book": c.book,
                   "price_american": c.price_american, "price_decimal": c.price_decimal, "model_prob": c.model_prob,
                   "market_prob": c.market_prob, "edge": c.edge, "edge_calibrated": c.edge_calibrated, "confidence": c.confidence,
                   "consensus_line": c.consensus_line, "open_line": c.open_line, "q50_live": c.q50_live, "sd": c.sd,
                   "factors": c.factors, "book_prices": c.book_prices, "event_id": c.event_id, "game_id": c.game_id}
        channel = "discord" if C.DISCORD_WEBHOOK_URL else ("telegram" if C.TELEGRAM_BOT_TOKEN else "none")
        if reason is not None:
            status, why = "suppressed", reason
        elif C.DRY_RUN:
            status, why = "not_sent", "dry_run"
        elif channel == "none":
            status, why = "not_sent", "no_webhook"
        else:
            status, why = "not_sent", "pending"     # flipped to sent on delivery
        aid = db.insert_returning_id("live_alerts", {
            "card_id": card_id, "live_snapshot_id": live_snapshot_id, "kind": kind, "channel": channel, "status": status,
            "reason": why, "dedupe_key": c.dedupe_key, "minutes_to_kick": round(mins, 1), "game_state_id": game_state_id,
            "stake_units": stake_for(c), "payload": payload})
        if reason is None:
            self.recent[c.dedupe_key] = (time.time(), c.edge)
        if status == "not_sent" and why == "pending":
            self.pending.append((aid, render(c, card_id, kind, extra)))
            self.first_pending_at = self.first_pending_at or time.time()
        tag = {"suppressed": f"suppressed ({why})", "not_sent": f"logged ({why})"}.get(status, status)
        print(f"[alert] {tag}: {c.player_name} {c.market} {c.side} {c.line:g} {fmt_american(c.price_american)} {c.book} "
              f"edge {c.edge:+.1%} conf {c.confidence} card={card_id}")
        return aid

    # ---------------------------------------------------------------- delivery
    def flush(self, force: bool = False):
        if not self.pending:
            return
        if not force and time.time() - (self.first_pending_at or 0) < C.ALERT_BATCH_SECONDS:
            return
        now = time.time()
        self.sent_times = [t for t in self.sent_times if now - t < 60]
        if len(self.sent_times) >= C.ALERT_MAX_PER_MINUTE:
            print("[alert] rate limit reached this minute; holding batch")
            return
        batch, self.pending = self.pending[:10], self.pending[10:]     # Discord: ≤10 embeds per message
        self.first_pending_at = time.time() if self.pending else None
        ids = [a for a, _ in batch]
        ok, msg_id, err = self._send([e for _, e in batch])
        self.sent_times.append(time.time())
        if ok:
            db.execute("UPDATE live_alerts SET status='sent', reason=NULL, sent_at=now(), message_id=:m WHERE id = ANY(:ids)",
                       {"m": msg_id, "ids": ids})
            print(f"[alert] sent {len(ids)} alert(s)")
        else:
            db.execute("UPDATE live_alerts SET status='not_sent', reason=:r WHERE id = ANY(:ids)", {"r": f"outage: {err}"[:200], "ids": ids})
            print(f"[alert] delivery failed: {err}")

    def _send(self, embeds: list[dict]) -> tuple[bool, str | None, str | None]:
        if C.DISCORD_WEBHOOK_URL:
            try:
                r = requests.post(C.DISCORD_WEBHOOK_URL, params={"wait": "true"}, json={"username": "NFL Edge Bot", "embeds": embeds},
                                  headers=UA, timeout=20)
                if r.status_code == 429:
                    time.sleep(float(r.headers.get("Retry-After", 2)))
                    r = requests.post(C.DISCORD_WEBHOOK_URL, params={"wait": "true"}, json={"username": "NFL Edge Bot", "embeds": embeds},
                                      headers=UA, timeout=20)
                r.raise_for_status()
                mid = None
                try:
                    mid = str(r.json().get("id"))
                except Exception:
                    pass
                self._telegram(embeds)
                return True, mid, None
            except Exception as e:
                return False, None, repr(e)
        if C.TELEGRAM_BOT_TOKEN:
            return self._telegram(embeds)
        return False, None, "no channel"

    def _telegram(self, embeds: list[dict]) -> tuple[bool, str | None, str | None]:
        if not (C.TELEGRAM_BOT_TOKEN and C.TELEGRAM_CHAT_ID):
            return False, None, "no telegram"
        try:
            text = "\n\n".join(f"*{e['title']}*\n{e['description']}" for e in embeds)
            r = requests.post(f"https://api.telegram.org/bot{C.TELEGRAM_BOT_TOKEN}/sendMessage",
                              json={"chat_id": C.TELEGRAM_CHAT_ID, "text": text[:4000], "parse_mode": "Markdown", "disable_web_page_preview": True},
                              timeout=20)
            r.raise_for_status()
            return True, str(r.json().get("result", {}).get("message_id")), None
        except Exception as e:
            return False, None, repr(e)

    def notice(self, text: str):
        """Operational message (start/stop/budget) — never a bet."""
        if C.DISCORD_WEBHOOK_URL and not C.DRY_RUN:
            try:
                requests.post(C.DISCORD_WEBHOOK_URL, json={"username": "NFL Edge Bot", "content": text[:1900]}, headers=UA, timeout=15)
            except Exception as e:
                print(f"[alert] notice failed: {e}")
