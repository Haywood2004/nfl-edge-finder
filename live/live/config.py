"""Live bot configuration. Everything here is an env var so the hosted worker is configured without code changes.
Secrets (DATABASE_URL, ODDS_API_KEY, DISCORD_WEBHOOK_URL, TELEGRAM_*) come from the host's env or the repo-root .env
(never committed). See docs/LIVE.md for the credit maths behind the defaults."""
from __future__ import annotations
import os
from nfl_edge.config import (ODDS_MONTHLY_CREDITS, PUBLISH_MIN_EDGE_BY_MARKET, PUBLISH_MIN_EDGE_PROPS,   # noqa: F401
                             PUBLISH_MIN_CONFIDENCE, MARKET_ANCHOR_W, NON_BETTABLE_BOOKS, SHARP_BOOK)

def _f(k, d): return float(os.environ.get(k, d))
def _i(k, d): return int(os.environ.get(k, d))
def _b(k, d): return os.environ.get(k, str(d)).strip().lower() in ("1", "true", "yes", "on")

# --- alert delivery ---------------------------------------------------------------------------------------
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
CARD_URL_BASE = os.environ.get("CARD_URL_BASE", "https://nfl-edge-finder.vercel.app")
ALERT_BATCH_SECONDS = _i("LIVE_ALERT_BATCH_SECONDS", 30)     # alerts within this window share one message
ALERT_MAX_PER_MINUTE = _i("LIVE_ALERT_MAX_PER_MINUTE", 5)    # Discord webhooks allow 30/min; stay well under
ALERT_COOLDOWN_HOURS = _f("LIVE_ALERT_COOLDOWN_HOURS", 6)    # same player/market/side/book/line: at most once per window
ALERT_REALERT_EDGE_GAIN = _f("LIVE_REALERT_EDGE_GAIN", 0.02) # ...unless the edge improved by this much
PAPER_ONLY = _b("LIVE_PAPER_ONLY", True)                     # four-week paper period (docs/AGENT_LIVE_BOT.md); cards never published
DRY_RUN = _b("LIVE_DRY_RUN", False)                          # price + log, send nothing (alerts logged not_sent/dry_run)

# --- credits ----------------------------------------------------------------------------------------------
# The pipeline spends ~2.5–3.5k/month. On the 20k plan the live bot gets a small slice; on the 100k plan ~90k.
LIVE_CREDIT_BUDGET = _i("LIVE_CREDIT_BUDGET", 5000)          # live bot's own monthly allowance (raise on the 100k plan)
STOP_AT_FRACTION = _f("LIVE_STOP_AT_FRACTION", 0.85)         # stop polling when the WHOLE key has used this share of the plan
PACING_BURST = _f("LIVE_PACING_BURST", 2.0)                   # may spend up to this × the even-pace allowance in an hour
PACING_HORIZON_HOURS = _f("LIVE_PACING_HORIZON_HOURS", 0)     # spread the remaining budget over this many hours (0 = rest of month)

# --- pre-game polling cadence (minutes) ---------------------------------------------------------------------
SWEEP_MIN = _i("LIVE_SWEEP_MIN", 360)          # every event-market at least this often (discovers new candidates)
HOT_MIN = _i("LIVE_HOT_MIN", 15)               # event-markets with a near-bar candidate
PREKICK_HOT_MIN = _i("LIVE_PREKICK_HOT_MIN", 5)   # ... in the final two hours
PREKICK_COLD_MIN = _i("LIVE_PREKICK_COLD_MIN", 20)
PREKICK_WINDOW_MIN = _i("LIVE_PREKICK_WINDOW_MIN", 120)
NEAR_BAR_MARGIN = _f("LIVE_NEAR_BAR_MARGIN", 0.03)   # candidate is "hot" when edge ≥ bar − margin
LOOP_SLEEP_SEC = _i("LIVE_LOOP_SLEEP_SEC", 30)
PREGAME_MARKETS = tuple(os.environ.get("LIVE_PREGAME_MARKETS", "player_pass_yds,player_reception_yds,player_receptions,player_rush_yds").split(","))

# --- in-game -----------------------------------------------------------------------------------------------
INGAME_ENABLED = _b("LIVE_INGAME_ENABLED", False)       # odds polling for live games (credits!). The ESPN state
                                                         # tracker + paper in-game projections run regardless (free).
INGAME_MARKETS = tuple(os.environ.get("LIVE_INGAME_MARKETS", "player_pass_yds,player_reception_yds").split(","))
INGAME_ODDS_MIN = _f("LIVE_INGAME_ODDS_MIN", 3)          # minutes between odds polls per live event
INGAME_STATE_SEC = _i("LIVE_INGAME_STATE_SEC", 20)       # ESPN scoreboard/summary cadence (cache 15s inside)
INGAME_SD_FLOOR = _f("LIVE_INGAME_SD_FLOOR", 0.20)       # sd_live ≥ this × pre-game sd
INGAME_USAGE_SHRINK_PLAYS = _f("LIVE_INGAME_USAGE_SHRINK", 25)   # usage_adj shrinks toward 1 with < this many team plays
INGAME_CLV_DELAY_SEC = _i("LIVE_INGAME_CLV_DELAY_SEC", 30)

ODDS_MONTHLY = ODDS_MONTHLY_CREDITS
