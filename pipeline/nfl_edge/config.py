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
# Publish bars, per market family (DECISIONS.md #24). Props: 6% — from the real closing-line backtest
# (2023–25: edge ≥6% → 446 bets, 55.6%, +6.5% ROI; ≥15% → 12 bets in three seasons). Moneylines keep
# the user's 15% bar because ML cards are venue price gaps, not model opinions.
PUBLISH_MIN_EDGE_PROPS = float(os.environ.get("PUBLISH_MIN_EDGE_PROPS", "0.06"))
PUBLISH_MIN_EDGE_ML = float(os.environ.get("PUBLISH_MIN_EDGE_ML", "0.15"))
PUBLISH_MIN_EDGE = PUBLISH_MIN_EDGE_PROPS   # back-compat alias
PUBLISH_MIN_CONFIDENCE = 55

# Scoring blends the model mean toward the consensus line: mean_used = (1-w)*model + w*line.
# Provisional (DECISIONS.md #7); refit once graded cards + CLV accumulate.
LEVEL_ANCHOR_W = float(os.environ.get("LEVEL_ANCHOR_W", "1.0"))   # share of the league-wide line-vs-model gap applied to every projection
MARKET_ANCHOR_W = float(os.environ.get("MARKET_ANCHOR_W", "0.2"))   # chosen on the real-line grid (backtest_lines.py)

US_BOOKS_REGION = "us"
PROP_MARKETS_V1 = [
    "player_pass_yds", "player_reception_yds", "player_rush_yds",
    "player_receptions", "player_pass_tds", "player_anytime_td",
]
GAME_MARKETS = ["h2h", "spreads", "totals"]
