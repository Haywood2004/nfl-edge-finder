# TODO.md

## Milestone 1 — vertical slice ✅ (demo notes)

What to look at:
- `python -m nfl_edge ingest_odds --from-dir <payload dir> --label tue_open` → snapshot 1: 554 lines, 5 books, 32 QBs.
- `python -m nfl_edge build_features` → 5,494 QB-game rows 2016–2025 + 32 for 2026 Week 1, 58 features, all `as_of < kickoff`.
- `python -m nfl_edge train` → `docs/MODEL.md`. Holdout MAE 58.0 vs 60.3 (rolling avg) / 64.5 (prior season).
- `python -m nfl_edge score` → 40 cards for Week 1; 1 clears edge ≥ 4% & confidence ≥ 55 on Tuesday lines (Herbert over). Most sit at confidence 52 because the injury report and forecasts aren't out — re-run after `ingest_injuries` + `ingest_weather` on Thursday.
- Web: `/` (published picks), `/board` (all 40), `/cards/<id>` (distribution, factors with source links, book-by-book, line movement, last-10 tables, injuries), `/rankings/defense` (the 1–32 table every rank links to), `/track-record` (empty until Week 1 is graded).
- `pytest` in `/pipeline`: 9 tests incl. the point-in-time assertions.

## Next (Milestone 1 hardening)
- [ ] Push repo to GitHub; add `ODDS_API_KEY` + `DATABASE_URL` secrets; create Neon/Supabase DB and run `db/schema.sql`; first Actions run.
- [ ] Deploy `/web` to Vercel with `DATABASE_URL`.
- [ ] Grade Week 1 on Tuesday 9/15 (`python -m nfl_edge grade`), check the track-record page renders real results.
- [ ] Refit `MARKET_ANCHOR_W` once ~3 weeks of grades/CLV exist.
- [ ] Line-movement factor needs ≥2 snapshots — verify after Thursday's snapshot.
- [ ] ESPN same-day injuries supplement (nflverse injuries publish Wed–Fri).
- [ ] `grades.closing_price_american` is a placeholder; store the actual closing price.

## Milestone 2
- [ ] Receiving yards / rushing yards / receptions models (same feature builder, different target + position).
- [ ] Coverage matchup layer (receiver → likely defender) from pbp alignment + depth charts; "unavailable" fallback.
- [ ] Injury redistribution (WR1 out → target share shift) from historical absences.

## Milestone 3–5
- [ ] Moneyline (Elo/EPA rating + QB-out adjustment), TD markets (Poisson).
- [ ] Trends engine (`@trend` decorator, auto backtest), Trends page, "Model + Trend" badge.
- [ ] CLV/calibration charts, Matchups page, Player page.
- [ ] Alerts (Discord/email), spreads & totals as bettable markets.
