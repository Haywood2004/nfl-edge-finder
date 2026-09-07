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

## 2026-09-04 — model v2 + redesign (demo notes)
- Look at: `/how` (live model card from `model_runs`), home hero KPIs, prop tiles with injury/regime factors once ESPN feed is reachable.
- Model v2 shipped: relative target + empirical residuals (calibration fixed), regime / script-neutral / injury / league-environment features, two-level market anchor. Weekly job now retrains passing yards every Tuesday.
- Open: ESPN injuries endpoint returned 403 from GitHub Actions runners (now sent with a browser UA; if still blocked, fall back to nflverse-only and the card says "report not published"). Odds API key appears to be on the 500-credit tier (~400 left) — upgrade before the Sunday snapshots or reduce the snapshot schedule.
- Next: refit MARKET_ANCHOR_W / LEVEL_ANCHOR_W from graded cards + CLV after ~6 weeks; receiving/rushing yards models (Milestone 2) reuse the v2 scaffolding; email capture / paid tier once the track record has a sample.

## From the Unabated playbook review (2026-09-04)
- [ ] Alternate lines: price every alt line each book posts from the same distribution (the data is already in `odds_lines`; backtest fixtures include BetRivers alternates). Highest-value derivative market on the "money tree".
- [ ] Injury-driven re-scoring Thu–Sun: make the ESPN feed reliable (403 from Actions runners) and add a "role change" factor when a teammate's status flips.
- [ ] First-half passing-yards props once a market source exists.
- [ ] Trends engine: each trend must declare a mechanism + min sample (≥100) and is badge-only.
- [ ] Never: same-game parlays, betting splits, RLM, futures without a simulator behind them.
- [ ] Sheet: add Rec Yds / Rush Yds / Receptions rows to the Model Stats block (re-upload build_gs.py output).
- [ ] Run `odds_history --markets player_reception_yds player_rush_yds player_receptions` (2023–25) and set per-market bars from the real-line tables.

## Requests from live bot (2026-09-07)
Filed by the live-bot agent (`docs/AGENT_LIVE_BOT.md`); these are pipeline/web changes the bot must not make itself.
- [ ] **Grader is passing-only.** `grading/grade.py` reads `raw_weekly_stats.passing_yards` for every card, so a
      receiving-yards / receptions / rushing card is graded against passing yards (0 for a WR → every Under "wins").
      Switch the stat column on `c.market` (and void on 0 targets/carries, as `backtest_lines.py` does). Live cards
      for those markets will be graded wrong until this lands; `python -m live report` grades market-aware itself.
- [ ] **Calibrator training set should exclude `source='live'` for now.** `models/calibration.py::_live_rows` joins
      `grades` to all `cards`; live paper alerts (weighted 3×) would leak into the pre-game calibrator. Add
      `AND c.source = 'model'` until a retrain with an `is_live` feature is agreed (brief: only via a PR with graded live rows).
- [ ] **Web: hide `source='live'` cards** from the screener's "Everything priced" and the track record during the paper
      period (`web/src/lib/queries.ts`; the rows are `published=false` but the board shows unpublished rows). A "Live" tab
      is the decision after four weeks.
- [ ] `db/schema.sql`: the two `ALTER TABLE cards … prob_calibrated/edge_calibrated` lines ran before `CREATE TABLE cards`
      and failed on a fresh database; moved to the end of the file in the live-bot PR (idempotent, no effect on existing DBs).
- [ ] `grades.closing_price_american` placeholder: the live bot stores the closing price in `live_clv`; happy to share code.

## Live bot — weekly paper report
Week 1 (kicks 2026-09-10): pending. Format: alerts · sent / not_sent / suppressed · W-L-P · units · mean CLV · %CLV>0 · credits.
