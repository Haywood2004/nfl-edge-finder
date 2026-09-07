# LIVE.md — the live edge bot (`/live`)

Owner: the live-bot agent (`docs/AGENT_LIVE_BOT.md`). The bot **alerts a human; it never places a bet**, never touches a
sportsbook login, and never modifies the pre-game models, features, scoring or web app. It writes only `live_*` tables
and `cards` rows with `source='live'` (enforced by `live/tests/test_writes.py`).

## Architecture

```
                 ┌──────────────── shared Postgres (Neon) ────────────────┐
                 │ projections · model_runs (pickles) · feat_player_game   │  read
                 │ odds_lines/odds_snapshots (open + Pinnacle) · raw_*     │
                 │ cards(source='live') · live_snapshots · live_lines      │  write
                 │ live_alerts · live_clv · live_game_state · live_projections
                 └────────────────────────────────────────────────────────┘
   The Odds API ──▶ live/odds.py ──▶ live/pricing.py ──▶ live/alerts.py ──▶ Discord / Telegram
   (per-event props)  Budget, LineStore   WeekContext.price()    cards + live_alerts
   ESPN scoreboard/summary ──▶ live/espn.py ──▶ live/tracker.py ──▶ live/ingame.py (mean_live, sd_live)
                                                                     └─▶ live_projections (paper, free)
                                                                     └─▶ (LIVE_INGAME_ENABLED) live odds → alerts → live_clv
   python -m live worker  = pre-game Watcher loop + in-game Tracker thread + CLV closer thread (one always-on process)
```

`live/pricing.py` does not re-implement anything: it imports the pipeline's model pickles (empirical residual ECDF →
P(over)), `confidence_score` / `skill_confidence`, the sharp ±, and the calibrator, and `tests/test_pricing_parity.py`
asserts that pricing the pipeline's own snapshot reproduces every card (model_prob, confidence, book, p_cal) exactly.

## Endpoints

| Source | Call | Cost | Cadence |
|---|---|---|---|
| The Odds API | `GET /v4/sports/americanfootball_nfl/events` | 0 | every 30 min (event ids, kickoff times) |
| The Odds API | `GET /v4/sports/americanfootball_nfl/events/{id}/odds?markets=<one>&regions=us` | 1 credit per market per event | adaptive, below |
| ESPN (public, no key) | `site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard` | free | every 20 s while games are live (15 s cache) |
| ESPN | `.../summary?event=<id>` (box score: per-player passing/rushing/receiving, team `totalOffensivePlays`) | free | same |
| Discord | webhook `POST`, ≤10 embeds per message | free | batched every 30 s, ≤5 messages/min |

Every Odds API call is logged in `api_usage` with `note = 'live:…'` so live spend is separable from the pipeline's.

## Polling cadence and credit maths

Pre-game, per (event, market) — 16 events × 4 markets = 64 event-markets a week:

| state | interval | env |
|---|---|---|
| cold (no candidate within 3% of the bar at the last poll) | 6 h | `LIVE_SWEEP_MIN` |
| hot (a candidate near or over the bar) | 15 min | `LIVE_HOT_MIN` |
| hot, inside 2 h of kickoff | 5 min | `LIVE_PREKICK_HOT_MIN` |
| cold, inside 2 h of kickoff | 20 min | `LIVE_PREKICK_COLD_MIN` |

Worst case (everything hot all week) is ~40k credits; typical weeks have 5–15 hot event-markets, ≈ 3–6k/week. Three
guards in `live/odds.py::Budget` keep it inside whatever the plan allows: (1) the bot's own monthly allowance
`LIVE_CREDIT_BUDGET` (5,000 on the 20k plan; set 90,000 on the 100k plan); (2) a hard stop when the key has used 85%
of `ODDS_MONTHLY_CREDITS` (read from the API's `x-requests-remaining` header, so the pipeline's spend counts too);
(3) hourly pacing — the remaining allowance is spread evenly over the hours left in the month and any hour may spend
at most 2× that (`LIVE_PACING_BURST`), so a hot Tuesday cannot eat the Sunday pre-kick window. When a guard trips the
poll is skipped and logged; nothing crashes.

In-game odds polling is **off by default** (`LIVE_INGAME_ENABLED=false`): 2 markets × ~13 concurrent games every 3 min
for a 3.5-hour slate is ≈ 1.8k credits per Sunday, which the 20k plan cannot afford next to the pipeline. The ESPN
tracker and the paper in-game projections (`live_projections`) run regardless, so the in-game model is validated live
against final box scores for free; flip the flag once the 100k plan is on.

## Storage rule (append-only, but not bloated)

Each poll inserts one `odds_snapshots` row (label `live_pregame` / `live_ingame`; `markets` prefixed `live:` so the
pipeline's "latest snapshot for market X" queries never select a live poll) — needed because `cards.snapshot_id`
references that table — plus one `live_snapshots` row with the live detail (event, credits, `n_lines`, `n_new`).
Lines go to `live_lines` **only when they differ** from the last stored line for the same (event, market, book, player,
side). At 5-minute polling the unchanged lines would be millions of rows a week; the `live_snapshots` row proves the
poll happened and `n_lines` says what was seen. Nothing is ever updated or deleted except `live_alerts.status`
(pending → sent / not_sent) on delivery.

## What an alert is

A `Candidate` (best-EV bettable book per player-side at this poll) that clears the pipeline's bar
(`PUBLISH_MIN_EDGE_BY_MARKET`: passing 6%, others 8%; confidence ≥ 55). On alert: a `cards` row is written with
`source='live'`, `published=false` (paper period), the exact line/price/book seen and `snapshot_id` → the grader and
CLV code work unchanged; a `live_alerts` row records channel/status/reason/stake/payload. Duplicate protection: the
same (player, market, side, book, line) is not re-alerted within 6 h unless the edge improved by ≥ 2%. Messages are
batched per 30 s window, at most 5 per minute; anything undeliverable is logged `not_sent` with the reason
(`rate_limit`, `outage:…`, `no_webhook`, `dry_run`). Stake = ¼ Kelly on the calibrated probability (`live/kelly.py`,
a port of `web/src/lib/kelly.ts` verified against 58 cases generated from the TypeScript).

Pre-game pricing detail: the stored projection median (already level- and market-anchored at scoring time) is
re-anchored to the *current* consensus with the scorer's weight, `q50_live = q50 + MARKET_ANCHOR_W·(cons_now −
cons_at_scoring)`, so a line that moves 3 yards moves our median 0.6 — exactly what the scorer would do at the next
snapshot. Confidence is recomputed with the pipeline's own function on the current line (so the line-move penalty
tracks the live line), the sharp ± uses Pinnacle from the last labelled snapshot, and the calibrator is applied as is
(it is a pre-game calibrator; in-game alerts say "uncalibrated for live").

## In-game model

`live/ingame.py`, validated by `python -m live replay` on 2025 play-by-play (results in `docs/MODEL.md`, "live"):
`mean_live = y_t + mean_pre · usage_adj · (1 − f) · script_adj`, `sd_live = sd_pre · remaining_share^k` (k per market,
0.40–0.60, floored at 20% of `sd_pre`). `f` = plays so far / (plays so far + pace-projected remaining plays);
`script_adj` = expected pass rate over the remaining time given the score state (table fitted on 2023–25 pbp) relative
to the team's pre-game rate; `usage_adj` = live share of team opportunities vs projected share, shrunk toward the
projection with few plays. 2025 replay: the live model beats the pre-game mean and naive pace at every checkpoint for
every market, and the ablation without usage/script terms from Q2 on; standardised errors have sd ≈ 1.0.

## CLV (the primary metric)

`live_clv` per alert and horizon. Pre-game: `close` = the last line before kickoff for the same book/player/market
(from `live_lines`, falling back to `odds_lines`), measured by the worker every 30 min (`python -m live clv`).
In-game: `30s` (one extra 1-credit poll 30 s after the alert) and `dead_ball` (the next clock change). `clv_prob` =
fair probability of our side at the horizon − at alert time (positive = the market moved toward us); `clv_line` is the
line move signed toward us.

## Paper period and reporting

Four weeks paper-only (`LIVE_PAPER_ONLY=true`): alerts are logged and graded, no live card is published on the site.
`python -m live report --days 7` prints alerts / sent / not_sent / suppressed, market-aware win-loss-push straight from
`raw_weekly_stats`, units, mean CLV and share of positive CLV, and credits — pasted weekly into `docs/TODO.md`.

## Running it

```
pip install -e pipeline -e live
python -m live status              # budget + context, no credits spent
LIVE_DRY_RUN=true python -m live pregame --once
python -m live worker              # the hosted entrypoint
cd live && pytest                  # 75 tests; DB-backed ones skip without DATABASE_URL
```

Schema: `python -m live migrate` applies the live block of `db/schema.sql` idempotently; the worker runs it on every start, so a fresh Neon database gets the `live_*` tables and `cards.source` without a manual step.

Hosting: one always-on worker (Fly.io `live/fly.toml` or Railway `live/railway.json`, Dockerfile in `live/`).
Secrets in the host's env: `DATABASE_URL`, `ODDS_API_KEY`, `DISCORD_WEBHOOK_URL` (optional `TELEGRAM_BOT_TOKEN`,
`TELEGRAM_CHAT_ID`). Knobs: `LIVE_CREDIT_BUDGET`, `LIVE_INGAME_ENABLED`, `LIVE_PAPER_ONLY`, `LIVE_DRY_RUN`, the
cadence variables above. Discord's API is blocked from the GitHub Actions runners and the development sandboxes, so
the worker host is the only place alerts can be sent from — which is also why the merge bar's 24-hour dry run has to be
done on the host (`LIVE_DRY_RUN=true`), not in CI.

## Demo note

`python -m live pregame --once` against the Week 1 fixture snapshot prices the 32 QBs (see the pricing-parity test),
stores a `live_snapshots` row per event-market with `n_new` = lines that changed, and logs any candidate over the bar to
`cards`/`live_alerts`. `python -m live replay --max-games 40` runs in ~5 s and prints the checkpoint table.
