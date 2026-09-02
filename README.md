# NFL Edge Finder

Surfaces NFL betting opportunities each week by comparing sportsbook lines against a
matchup-aware projection model. Every flagged card explains *why* in verifiable factors.

```
/web        Next.js app (App Router, Tailwind, Drizzle)
/pipeline   Python: ingest → features → models → scoring → grading
/db         schema.sql + migrations
/docs       DECISIONS.md, TODO.md, MODEL.md, DATA_SOURCES.md
```

## Quick start

```bash
cp .env.example .env            # fill in ODDS_API_KEY and DATABASE_URL
psql "$DATABASE_URL" -f db/schema.sql
cd pipeline && pip install -e . && python -m nfl_edge bootstrap   # ingest everything, train, score
cd ../web && npm install && npm run dev
```

Individual jobs: `python -m nfl_edge <job>` where job ∈
`ingest_schedule ingest_pbp ingest_weekly_stats ingest_injuries ingest_depth_charts ingest_snaps ingest_odds ingest_weather build_features train score grade`.

Informational only — not financial advice. If you or someone you know has a gambling problem, call 1-800-GAMBLER.
