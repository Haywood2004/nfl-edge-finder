"""Polymarket NFL game markets (free, no key).

Gamma API: https://gamma-api.polymarket.com
  GET /events?slug=nfl-{away}-{home}-{YYYY-MM-DD}     (date = kickoff date in UTC)
  GET /public-search?q=<Away> <Home>                   fallback
Each event carries markets with `sportsMarketType` in {moneyline, spreads, totals}; `outcomePrices`
are the current mid prices in [0,1] (they already sum to ~1 for a two-way market, i.e. ~no vig).
We convert a price p to decimal odds 1/p and store rows as bookmaker='polymarket'.

Polymarket is a prediction market, not a sportsbook: prices reflect where traders will deal, and
liquidity on smaller games can be thin. It is treated as one more "book" in consensus/best-price and
is surfaced on cards as its own factor ("Polymarket vs books").
"""
from __future__ import annotations
import re
import requests
from ..teams import ABBR_TO_NAME

BASE = "https://gamma-api.polymarket.com"
NICK_TO_ABBR = {name.split()[-1]: abbr for abbr, name in ABBR_TO_NAME.items()}
NICK_TO_ABBR["49ers"] = "SF"
# Polymarket slug abbreviations differ from nflverse for a few teams
SLUG_ABBR = {"LA": "la", "JAX": "jax", "WAS": "was", "LV": "lv", "LAC": "lac", "GB": "gb", "KC": "kc",
             "NE": "ne", "NO": "no", "SF": "sf", "TB": "tb", "NYG": "nyg", "NYJ": "nyj"}


def slug_for(away: str, home: str, kickoff_utc) -> str:
    a = SLUG_ABBR.get(away, away.lower())
    h = SLUG_ABBR.get(home, home.lower())
    return f"nfl-{a}-{h}-{kickoff_utc:%Y-%m-%d}"


def fetch_event(away: str, home: str, kickoff_utc, session: requests.Session | None = None) -> dict | None:
    s = session or requests.Session()
    for slug in (slug_for(away, home, kickoff_utc), slug_for(away, home, kickoff_utc).replace("-la-", "-lar-")):
        r = s.get(f"{BASE}/events", params={"slug": slug}, timeout=30)
        if r.ok and r.json():
            return r.json()[0]
    q = f"{ABBR_TO_NAME[away].split()[-1]} {ABBR_TO_NAME[home].split()[-1]}"
    r = s.get(f"{BASE}/public-search", params={"q": q, "limit_per_type": 5}, timeout=30)
    if r.ok:
        for ev in r.json().get("events", []):
            if ev.get("slug", "").startswith("nfl-") and kickoff_utc.strftime("%Y-%m-%d") in ev.get("slug", ""):
                return ev
    return None


def _prices(m: dict) -> list[float] | None:
    import json
    p = m.get("outcomePrices")
    if isinstance(p, str):
        p = json.loads(p)
    o = m.get("outcomes")
    if isinstance(o, str):
        o = json.loads(o)
    if not p or not o or len(p) != len(o):
        return None
    m["_outcomes"] = o
    return [float(x) for x in p]


def lines_from_event(ev: dict, away: str, home: str) -> list[dict]:
    """→ rows shaped like odds_lines (minus snapshot/event ids). Only two-way markets with prices in (0,1)."""
    rows = []
    for m in ev.get("markets", []):
        kind = m.get("sportsMarketType")
        p = _prices(m)
        if not p or kind not in ("moneyline", "spreads", "totals") or m.get("closed"):
            continue
        outs = m["_outcomes"]
        q = m.get("question", "")
        if kind == "moneyline":
            market, line = "h2h", None
            sides = [ABBR_TO_NAME.get(NICK_TO_ABBR.get(o, ""), o) for o in outs]
        elif kind == "spreads":
            mm = re.search(r"\(([-+]?\d+(?:\.\d+)?)\)", q)
            if not mm:
                continue
            fav_pt = float(mm.group(1))
            market = "spreads"
            fav_nick = q.split(":", 1)[-1].split("(")[0].strip()
            sides, pts = [], []
            for o in outs:
                sides.append(ABBR_TO_NAME.get(NICK_TO_ABBR.get(o, ""), o))
                pts.append(fav_pt if o == fav_nick else -fav_pt)
            line = pts
        else:
            mm = re.search(r"O/U\s*(\d+(?:\.\d+)?)", q)
            if not mm:
                continue
            market, line = "totals", float(mm.group(1))
            sides = outs
        for i, (side, price) in enumerate(zip(sides, p)):
            if not (0.01 <= price <= 0.99):
                continue
            dec = round(1 / price, 4)
            rows.append({"market": market, "bookmaker": "polymarket", "book_title": "Polymarket",
                         "player": None, "side": side,
                         "line": (line[i] if isinstance(line, list) else line),
                         "price_decimal": dec, "price_american": _american(dec),
                         "book_last_update": m.get("updatedAt")})
    return rows


def _american(decimal: float) -> int:
    return int(round((decimal - 1) * 100)) if decimal >= 2 else int(round(-100 / (decimal - 1)))
