# DECISIONS.md

Running log of decisions made while building NFL Edge Finder. Newest at the bottom.

1. **nflverse loaded straight from GitHub release assets, not `nfl_data_py`.** `nfl_data_py`'s schedule loader points at a third-party mirror that is not reachable from every environment, and the package is deprecated in favour of nflreadpy. `pipeline/nfl_edge/sources/nflverse.py` downloads the same parquet/csv assets, caches them in `pipeline/.cache`, and never re-downloads completed seasons.

2. **Odds team names → nflverse abbreviations via a static map** (`teams.py`). Event ↔ game matching uses (home, away, kickoff within 36h). Historical relocations (OAK/SD/STL) are normalised to LV/LAC/LA so rolling features survive moves.

3. **Odds ingest can replay recorded payloads** (`--from-dir`). The build environment could not open a socket to api.the-odds-api.com, so Week 1 was ingested from payloads fetched out-of-band and stored as `odds_snapshots.source='file'`. Credits for those calls were logged manually into `api_usage` (22 credits). In GitHub Actions the client hits the API directly; nothing else differs.

4. **`raw_pbp` stores a curated 50-column subset** of the ~370 nflverse columns (the ones the feature layer uses: play type, EPA, air yards, passers/receivers/rushers, situational fields). The full parquet stays in the cache, so widening is a one-line change to `PBP_COLS` plus a re-run — the raw shape is otherwise preserved.

5. **Point-in-time features by week boundary.** A row for (season, week) uses games with `week < target` in that season plus prior seasons; `as_of` = earliest kickoff of that week − 6h. This is slightly stricter than kickoff-by-kickoff (a Sunday game ignores that week's Thursday game) and makes leakage impossible by construction. Tested in `tests/test_leakage.py`.

6. **Early-season blending.** Team features blend current season with the prior season using K = 6 games-equivalent, and the prior season is first shrunk 50% toward the league mean (defenses regress hard year over year). Week 1 is therefore "last year shrunk 50%", and the card says so in an explicit `early_season` factor.

7. **Market anchoring in scoring (provisional).** The scored mean is `0.65 × model + 0.35 × consensus line`. Rationale: with no historical prop lines to train against, the market line is the best available public estimate, and a model that ignores it entirely flags many false edges (Week 1 unders everywhere, because books price offseason information the stats can't see). The raw model mean is stored in `projections`; only `cards` use the anchored mean. `MARKET_ANCHOR_W` lives in `config.py` and should be refit once a few weeks of graded cards + CLV exist.

8. **Distribution = Normal with heteroscedastic sd** (second LightGBM predicting |residual| on out-of-fold residuals, calibrated on the validation season). Simpler than quantile regression and the holdout coverage is good (q10/q25/q75/q90 → .097/.279/.785/.920). Revisit if a market with a skewed target (receptions, TDs) needs it.

9. **No historical prop lines → no real closing-line ROI backtest.** MODEL.md reports MAE vs naive baselines, quantile coverage, P(over) calibration, and a *labelled proxy* betting sim against a player-only model. Real ROI/CLV accrues from live snapshots only. This is stated on the page and in MODEL.md rather than papered over.

10. **Confidence starts at 72 and only subtracts.** Penalties: small career sample, thin prior season, new team, Week 1 / early season, missing injury report, missing weather forecast, few books, line moved against us, and implausibly large edge (>10%/>15%). Tuesday cards routinely land at ~52 (< 55) until the Wednesday/Thursday injury report and forecast arrive, which is the intended behaviour: don't flag before the information exists.

11. **Cards, projections, odds, injuries, grades are append-only.** A rescore inserts a new batch; the web app shows the latest batch (max `created_at`) for the target week and keeps old batches queryable. Pre-launch dev batches from a known-buggy run (PROE units) were deleted before the first publish; nothing is deleted after.

12. **Web app reads Postgres through Drizzle's `postgres-js` driver with raw SQL** rather than a full Drizzle schema — the schema of record is `db/schema.sql`, and duplicating 27 tables in TypeScript before the shape settles would just be drift. Typed row shapes live in `web/src/lib/queries.ts`.

13. **Weather via Open-Meteo is best-effort.** Not reachable from the build sandbox; the job runs in Actions. Until a forecast exists, outdoor cards carry a "forecast unavailable" factor and −4 confidence.

14. **Moneyline model is anchored 95% to the sportsbook consensus, and moneyline cards flag price discrepancies, not model opinions.** Validation (2024) chose the anchor by log-loss; the walk-forward backtest against real nflverse closing moneylines (2019–2025) shows the raw Elo/EPA model losing 10–14% ROI at every edge threshold, including ≥15%. Full tables in MODEL.md. So the useful signal on moneylines is cross-venue pricing (e.g. Polymarket vs books), plus CLV over the week.

15. **Polymarket is ingested as bookmaker `polymarket` in the same snapshot as The Odds API** (Gamma API, free). Its prices are mid quotes with no vig, so it is haircut by 1.5¢ when used as a "best price" and marked as such on cards; it also feeds a `polymarket` factor (traders vs books gap).

16. **Publish threshold raised to edge ≥ 15% at the user's request (2026-09-03).** Given the backtests, this bar will rarely be met on moneylines and only occasionally on props; the home page therefore shows the closest-to-the-bar picks and every game's probability track, and the full board keeps everything. Revisit once graded results exist.

17. **Home page redesigned around visuals**: games grid with a home-win-probability track (model / books / Polymarket markers, validated categorical palette), edge meters against the bar, compact prop tiles. Text-heavy card detail remains one click away.
