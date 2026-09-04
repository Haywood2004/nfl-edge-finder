from __future__ import annotations
import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/nfl_edge")
ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "")
ODDS_MONTHLY_CREDITS = int(os.environ.get("ODDS_MONTHLY_CREDITS", "20000"))
ODDS_CREDIT_ALERT_FRACTION = float(os.environ.get("ODDS_CREDIT_ALERT_FRACTION", "0.70"))

CACHE_DIR = Path(os.environ.get("NFL_EDGE_CACHE", ROOT / "pipeline" / ".cache"))
ARTIFACT_DIR = ROOT / "pipeline" / "artifacts"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

FIRST_TRAIN_SEASON = 2016

# Card publication thresholds (brief §4.5). Tune on backtests; see docs/MODEL.md.
PUBLISH_MIN_EDGE = 0.15   # user-set bar (2026-09-03); everything below stays on the full board
PUBLISH_MIN_CONFIDENCE = 55

# Scoring blends the model mean toward the consensus line: mean_used = (1-w)*model + w*line.
# Provisional (DECISIONS.md #7); refit once graded cards + CLV accumulate.
LEVEL_ANCHOR_W = float(os.environ.get("LEVEL_ANCHOR_W", "0.5"))   # share of the league-wide line-vs-model gap applied to every projection
MARKET_ANCHOR_W = 0.35

US_BOOKS_REGION = "us"
PROP_MARKETS_V1 = [
    "player_pass_yds", "player_reception_yds", "player_rush_yds",
    "player_receptions", "player_pass_tds", "player_anytime_td",
]
GAME_MARKETS = ["h2h", "spreads", "totals"]
