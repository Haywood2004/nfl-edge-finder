# Live edge bot worker (docs/LIVE.md). Build from the repo root:  docker build -f live/Dockerfile -t nfl-edge-live .
FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 NFL_EDGE_CACHE=/tmp/nfl_edge_cache
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pipeline/pyproject.toml pipeline/pyproject.toml
COPY pipeline/nfl_edge pipeline/nfl_edge
COPY live/pyproject.toml live/pyproject.toml
COPY live/live live/live
COPY docs docs
RUN pip install -e pipeline -e live
# secrets come from the host's environment: DATABASE_URL, ODDS_API_KEY, DISCORD_WEBHOOK_URL (+ LIVE_* overrides)
CMD ["python", "-m", "live", "worker"]
