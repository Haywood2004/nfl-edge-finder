# DATA_SOURCES.md

## nflverse (free) — `pipeline/nfl_edge/sources/nflverse.py`
Base: `https://github.com/nflverse/nflverse-data/releases/download/`

| Asset | URL pattern | Loaded into | Notes |
|---|---|---|---|
| Schedules | `schedules/games.csv` | `raw_games` | 1999+. `spread_line` is home-relative, positive = home favored; `total_line`; `roof`; `gametime` ET → `kickoff_utc`. Lines for upcoming weeks are present. |
| Play-by-play | `pbp/play_by_play_{season}.parquet` | `raw_pbp` (50-col subset) | ~48k rows/season. `passing_yards` is gross (excludes sacks). `pass_oe` is in **percent**. Published for a season once Week 1 is played. |
| Weekly player stats | `stats_player/stats_player_week_{season}.parquet` | `raw_weekly_stats` | 150 cols; we keep passing/rushing/receiving core + shares. `player_id` = gsis id. |
| Injuries | `injuries/injuries_{season}.parquet` | `raw_injuries` (append-only history) | Wed–Fri practice + game status. |
| Depth charts | `depth_charts/depth_charts_{season}.parquet` | `raw_depth_charts` | Daily `dt`; QB1 = `pos_abb='QB' AND pos_rank=1` at latest `dt ≤ as_of`. |
| Rosters | `rosters/roster_{season}.parquet` | `raw_rosters` | name/position/exp/headshot. |
| Snap counts | `snap_counts/snap_counts_{season}.parquet` | `raw_snap_counts` | PFR ids. |

Rate limits: none (GitHub releases). Cache: `pipeline/.cache`, 12h TTL in season, completed seasons cached forever.

## The Odds API (paid, $30/mo = 20k credits) — `sources/odds_api.py`
Base: `https://api.the-odds-api.com/v4`, key via `ODDS_API_KEY`, `regions=us`, `oddsFormat=decimal`.

| Endpoint | Cost | Used for |
|---|---|---|
| `GET /sports/americanfootball_nfl/events` | 0 | Event ids, kickoff, team names → `odds_events` |
| `GET /sports/americanfootball_nfl/odds?markets=h2h,spreads,totals` | 3 (markets × regions) | Game lines for all listed events |
| `GET /sports/americanfootball_nfl/events/{id}/odds?markets=player_pass_yds,...` | 1 per market per region per event | Props (per event only) |

Headers `x-requests-used / x-requests-remaining / x-requests-last` are written to `api_usage` on every call; warning printed past 70% of the monthly budget. Weekly budget at the §4.4 schedule: 16 events × 6 markets × 5 snapshots ≈ 480 + game lines; Milestone 1 uses 1 market (16/snapshot).

Field mapping: `bookmakers[].key` → `odds_lines.bookmaker`; `markets[].outcomes[]`: `name` → `side` (Over/Under/team), `description` → `player`, `point` → `line`, `price` → `price_decimal` (American derived). Books seen for NFL props: draftkings, fanduel, betmgm, betrivers, bovada, betonlineag (+ others in-season).

No-vig: proportional de-vig per book two-way; `odds_consensus` stores mean no-vig prob across books and best price per side.

## Open-Meteo (free) — `ingest/weather_jobs.py`
`GET https://api.open-meteo.com/v1/forecast?latitude&longitude&hourly=temperature_2m,wind_speed_10m,precipitation,precipitation_probability&temperature_unit=fahrenheit&wind_speed_unit=mph&timezone=UTC&forecast_days=16`. Stadium coordinates in `teams.py`. Domes skipped. Failures logged, never fatal.

## Public sanity check
2025 pass-defense yards/game from `feat_team_defense` matched StatMuse to the hundredth (BUF 170.24 … DAL 265.94).
