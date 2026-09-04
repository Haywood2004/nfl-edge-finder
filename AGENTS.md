# AGENTS.md — brief for any AI (or human) working on NFL Edge Finder

Read this before touching anything. It is the contract every contributor works under; the docs it points to
hold the details.

## What this is
A matchup-aware NFL betting edge finder. `/pipeline` (Python: ingest → point-in-time features → models →
scoring → grading) writes to Postgres (Neon); `/web` (Next.js) reads it. GitHub Actions runs the pipeline on
the snapshot schedule in `.github/workflows/pipeline.yml`. Map: `docs/DECISIONS.md` (numbered decisions and
why), `docs/MODEL.md` (every retrain's metrics), `docs/DATA_SOURCES.md` (endpoints, credits, field maps),
`docs/TODO.md` (roadmap + demo notes).

## Betting philosophy (aligned with the Unabated "five questions" — see DECISIONS.md #25)
1. **Trust only information the market has not already priced.** No betting splits, no reverse-line-movement,
   no "public vs sharp" narratives — they come from recreational books and are noise. Line movement is a
   small confidence input, never a signal on its own.
2. **Attack markets that can be beaten.** Player props first (softest, most surface area, books tolerate
   them). Full-game sides and totals are the most efficient market in US sports and are v2 inputs only, never
   picks. Moneylines are published only as venue price gaps, because the ratings model loses to the closing
   line (MODEL.md).
3. **Express the opinion in the right instrument.** A projection distribution prices *any* line, so alternate
   lines and derivatives are fair game once modelled; same-game parlays are never recommended (correlation is
   mispriced against the bettor).
4. **Bet early, grade at the close.** Snapshots start Tuesday open; a paper bet locks at the first snapshot
   that clears the bar; closing-line value is recorded on every graded pick.
5. **Repeatable every week or it does not exist.** Everything runs from cron; nothing depends on a person
   remembering to update ratings.
Trends (roadmap) must state a quantifiable mechanism and a minimum sample before they can badge a card; a
trend never publishes a pick on its own. Books deal a *median* line; the model's P(over) comes from the full
distribution (empirical residuals), not from comparing a mean to the line.

## Invariants — a PR that breaks one is rejected regardless of backtest gains
- **Point-in-time.** A feature row for (season, week) uses only data available before that week's first
  kickoff − 6h. `tests/test_leakage.py` checks `as_of < kickoff`; it cannot catch a rolling window that
  peeks, so think about it yourself. Injury/depth-chart inputs for week w are the reports for week w.
- **Append-only.** Odds snapshots, cards, projections, injury statuses, model runs: insert, never update or
  delete. Re-runs must be idempotent (natural-key upserts).
- **Grade at the published price.** `grades` use the price on the card when it was published. Losses are shown.
- **Explainability.** Every published card carries `factors[]` a human can verify against a table in the DB.
  A feature that cannot be explained on a card should not exist.
- **Graceful degradation.** A missing source lowers confidence and is labelled; it never crashes a job or
  silently hides a card.
- **Responsible gambling copy stays** (footer, 1-800-GAMBLER, no "locks").

## The referee: real closing-line backtest
`pipeline/fixtures/odds_history/<season>.parquet` holds every US book's closing prop line for 2023–2025.
```
cd pipeline && python -m nfl_edge backtest_lines      # ~3 min, no API, no secrets beyond DATABASE_URL
```
It fits walk-forward, prices exactly as `scoring/cards.py` does, and reports bets / win rate / ROI by edge
threshold and season, plus the anchor-weight grid. **Merge bar:** ROI at edge ≥ 6% does not get worse overall
and does not flip negative in more than one season; MAE and calibration (walk-forward holdout in
`python -m nfl_edge train`) do not degrade; `pytest` passes. Report the before/after tables in the PR.
Historical lines cost credits (10 per market per event); ask before fetching a new market
(`python -m nfl_edge odds_history --seasons ... --markets ...`).

## Running locally
Postgres with `db/schema.sql`; `.env` with `DATABASE_URL` (+ `ODDS_API_KEY` only for live odds).
`python -m nfl_edge bootstrap` loads nflverse 2016+ (GitHub releases; no key). Jobs are in
`pipeline/nfl_edge/cli.py`. Web: `cd web && npm run dev`.

## Division of labour
Own a module, not a file. Each market gets its own `models/<market>.py` + scoring hooks; shared code
(`features/`, `scoring/factors.py`, `db.py`) changes need the backtest table and a DECISIONS.md entry.
Document every non-obvious choice as a numbered decision; the next agent reads those first.
