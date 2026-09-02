"""The Odds API client with credit accounting.

Endpoints (https://the-odds-api.com/liveapi/guides/v4/):
  GET /v4/sports/{sport}/events                       free (0 credits)
  GET /v4/sports/{sport}/odds?markets=h2h,spreads,totals&regions=us
        cost = markets × regions = 3 credits for all games
  GET /v4/sports/{sport}/events/{id}/odds?markets=player_pass_yds,...&regions=us
        cost = markets × regions per event (1 credit per market per region)
Response headers x-requests-used / x-requests-remaining / x-requests-last are logged to api_usage.

Every call can alternatively be replayed from a recorded JSON payload (source="file") so the
pipeline runs in environments without egress to the API — see DECISIONS.md #3.
"""
from __future__ import annotations
import json
from pathlib import Path
import requests
from .. import db
from ..config import ODDS_API_KEY, ODDS_MONTHLY_CREDITS, ODDS_CREDIT_ALERT_FRACTION

BASE = "https://api.the-odds-api.com/v4"
SPORT = "americanfootball_nfl"


class OddsAPI:
    def __init__(self, api_key: str | None = None, session: requests.Session | None = None):
        self.key = api_key or ODDS_API_KEY
        self.s = session or requests.Session()
        self.last_headers: dict = {}

    def _get(self, path: str, params: dict, note: str = "") -> list | dict:
        if not self.key:
            raise RuntimeError("ODDS_API_KEY not set")
        r = self.s.get(f"{BASE}{path}", params={**params, "apiKey": self.key}, timeout=60)
        self.last_headers = dict(r.headers)
        used = int(r.headers.get("x-requests-last", 0) or 0)
        remaining = r.headers.get("x-requests-remaining")
        remaining = int(remaining) if remaining is not None else None
        db.append(__import__("pandas").DataFrame([{
            "endpoint": path, "credits_used": used, "credits_remaining": remaining, "note": note or None,
        }]), "api_usage")
        if remaining is not None and remaining < ODDS_MONTHLY_CREDITS * (1 - ODDS_CREDIT_ALERT_FRACTION):
            print(f"[odds] WARNING credit usage above {ODDS_CREDIT_ALERT_FRACTION:.0%}: {remaining} remaining")
        r.raise_for_status()
        return r.json()

    def events(self) -> list[dict]:
        return self._get(f"/sports/{SPORT}/events", {}, "events")

    def game_odds(self, markets=("h2h", "spreads", "totals"), regions="us") -> list[dict]:
        return self._get(f"/sports/{SPORT}/odds",
                         {"markets": ",".join(markets), "regions": regions, "oddsFormat": "decimal"}, "game_odds")

    def event_odds(self, event_id: str, markets: tuple[str, ...], regions="us") -> dict:
        return self._get(f"/sports/{SPORT}/events/{event_id}/odds",
                         {"markets": ",".join(markets), "regions": regions, "oddsFormat": "decimal"},
                         f"event_odds:{event_id}")


def load_payload(path: str | Path):
    """Load a recorded API payload. Tolerates a ```json fence around the body."""
    t = Path(path).read_text().strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1]
        t = t.rsplit("```", 1)[0]
    return json.loads(t)


def american(decimal: float) -> int:
    if decimal >= 2.0:
        return int(round((decimal - 1) * 100))
    return int(round(-100 / (decimal - 1)))


def implied(decimal: float) -> float:
    return 1.0 / decimal


def no_vig_two_way(p_over: float, p_under: float) -> tuple[float, float]:
    """Multiplicative (proportional) de-vig of a two-way market."""
    s = p_over + p_under
    return p_over / s, p_under / s
