"""Python port of web/src/lib/kelly.ts — must stay numerically identical (tests/test_kelly.py checks 50 fixtures
generated from the TypeScript). Stake sizing for alerts: ¼ Kelly, 3% cap, 0.05u steps, 0.1u floor, 40% weekly exposure."""
from __future__ import annotations
import math

DEFAULT_BANKROLL = 100.0
DEFAULT_FRACTION = 0.25
MIN_STAKE = 0.1
MAX_STAKE_PCT = 0.03
WEEKLY_EXPOSURE_PCT = 0.40


def exposure_scale(stakes: list[float], bankroll: float = DEFAULT_BANKROLL, exposure_pct: float = WEEKLY_EXPOSURE_PCT) -> float:
    total = sum(stakes)
    budget = bankroll * exposure_pct
    return budget / total if (total > budget and total > 0) else 1.0


def kelly_full(p: float, dec: float) -> float:
    b = dec - 1
    if b <= 0:
        return 0.0
    return (p * b - (1 - p)) / b


def _js_round(x: float) -> float:
    """JavaScript Math.round: half rounds toward +∞ (Python's round() is banker's rounding)."""
    return math.floor(x + 0.5)


def kelly_stake(p: float, dec: float, bankroll: float = DEFAULT_BANKROLL, fraction: float = DEFAULT_FRACTION) -> float:
    f = kelly_full(p, dec)
    if f <= 0:
        return 0.0
    raw = min(f * fraction, MAX_STAKE_PCT) * bankroll
    rounded = _js_round(raw * 20) / 20
    return 0.0 if rounded < MIN_STAKE else rounded
