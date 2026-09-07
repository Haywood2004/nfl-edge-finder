"""In-game projection model (minimum viable, docs/AGENT_LIVE_BOT.md):

  mean_live = y_t + mean_pre · usage_adj · remaining_share
  sd_live   = sd_pre · remaining_share^SD_EXP[market]   (≈ sqrt; tuned per market) floored at INGAME_SD_FLOOR · sd_pre

where
  y_t             the player's stat so far
  remaining_share expected remaining opportunities (dropbacks for passing/receiving, rushes for rushing) as a share of
                  the pre-game expected total; = (1 − f) · script_adj in the brief's notation, with f the fraction of
                  expected team plays elapsed (plays so far vs. plays so far + pace-projected remaining plays) and
                  script_adj the score-state pass-rate multiplier for the rest of the game (SCRIPT_TABLE, fitted on
                  2023–25 play-by-play: pass rate by game phase × score differential, relative to neutral)
  usage_adj       the player's live share of team opportunities vs. his projected share, shrunk toward 1 with few plays

Pure functions so `replay.py` (validation on 2025 play-by-play) and `tracker` (live ESPN state) share the code.
"""
from __future__ import annotations
import math
from dataclasses import dataclass
from . import config as C

NEUTRAL_PASS_RATE = 0.585    # 2023–25, |score diff| ≤ 3, Q1–Q3
# expected pass rate by phase (Q1, Q2, Q3, Q4 first 10 min, Q4 last 5 min) × score differential bucket
SCRIPT_BUCKETS = [(-99, -14), (-14, -7), (-7, -3), (-3, 3), (3, 7), (7, 14), (14, 99)]
SCRIPT_TABLE = {
    "Q1":  [0.583, 0.583, 0.575, 0.568, 0.562, 0.549, 0.571],
    "Q2":  [0.695, 0.658, 0.635, 0.626, 0.637, 0.636, 0.613],
    "Q3":  [0.651, 0.599, 0.561, 0.562, 0.593, 0.549, 0.503],
    "Q4a": [0.804, 0.720, 0.596, 0.568, 0.531, 0.456, 0.360],
    "Q4b": [0.803, 0.906, 0.826, 0.573, 0.298, 0.222, 0.168],
}
PHASES = [("Q1", 3600, 2700), ("Q2", 2700, 1800), ("Q3", 1800, 900), ("Q4a", 900, 300), ("Q4b", 300, 0)]
LEAGUE_PLAYS_PG = 63.0
# sd_live = sd_pre · remaining_share ** SD_EXP[market]. 0.5 is the independent-increments answer; the 2025 replay showed
# passing variance shrinks slower than that late in games (garbage time) and rushing faster (clock-killing), so the
# exponent is tuned per market to bring the standardised error's sd to ≈1 at every checkpoint (docs/MODEL.md, "Live").
SD_EXP = {"player_pass_yds": 0.40, "player_reception_yds": 0.48, "player_receptions": 0.45, "player_rush_yds": 0.60}
PACE_SHRINK_PLAYS = 20.0     # live pace is trusted fully after ~20 plays


def bucket_index(score_diff: float) -> int:
    for i, (lo, hi) in enumerate(SCRIPT_BUCKETS):
        if lo <= score_diff < hi:
            return i
    return len(SCRIPT_BUCKETS) - 1


def expected_pass_rate_remaining(secs_remaining: float, score_diff: float) -> float:
    """Time-weighted expected pass rate over the remaining regulation time given the current score state."""
    if secs_remaining <= 0:
        return NEUTRAL_PASS_RATE
    b = bucket_index(score_diff)
    tot, acc = 0.0, 0.0
    for name, start, end in PHASES:
        span = max(0.0, min(secs_remaining, start) - end)
        if span > 0:
            acc += SCRIPT_TABLE[name][b] * span
            tot += span
    return acc / tot if tot else NEUTRAL_PASS_RATE


def expected_remaining_plays(plays_so_far: int, secs_elapsed: float, secs_remaining: float, team_plays_pg: float | None) -> float:
    pre_rate = (team_plays_pg or LEAGUE_PLAYS_PG) / 3600.0
    if secs_elapsed > 60 and plays_so_far > 0:
        live_rate = plays_so_far / secs_elapsed
        w = plays_so_far / (plays_so_far + PACE_SHRINK_PLAYS)
        rate = w * live_rate + (1 - w) * pre_rate
    else:
        rate = pre_rate
    return max(rate * secs_remaining, 0.0)


@dataclass
class LiveProjection:
    mean_live: float
    sd_live: float
    f: float
    usage_adj: float
    script_adj: float
    remaining_share: float


def project(market: str, y_t: float, mean_pre: float, sd_pre: float, *, plays_so_far: int, secs_elapsed: float,
            secs_remaining: float, score_diff: float, team_plays_pg: float | None, team_pass_rate: float | None,
            team_opps_so_far: int, player_opps_so_far: int, share_pre: float | None,
            sd_floor: float = C.INGAME_SD_FLOOR, usage_shrink: float = C.INGAME_USAGE_SHRINK_PLAYS) -> LiveProjection:
    """market: player_pass_yds | player_reception_yds | player_receptions | player_rush_yds.
    team_opps_so_far / player_opps_so_far: dropbacks & the player's attempts/targets (passing/receiving) or rushes & carries."""
    passing = market != "player_rush_yds"
    pr_pre = team_pass_rate if team_pass_rate else NEUTRAL_PASS_RATE
    plays_pg = team_plays_pg or LEAGUE_PLAYS_PG
    rem_plays = expected_remaining_plays(plays_so_far, secs_elapsed, secs_remaining, plays_pg)
    f = plays_so_far / (plays_so_far + rem_plays) if (plays_so_far + rem_plays) > 0 else 1.0
    pr_rem = expected_pass_rate_remaining(secs_remaining, score_diff)
    # scale the score-state rate by the team's own tendency relative to league neutral
    pr_rem_team = min(max(pr_rem * (pr_pre / NEUTRAL_PASS_RATE), 0.2), 0.9)
    opp_rate_rem = pr_rem_team if passing else (1 - pr_rem_team)
    opp_rate_pre = pr_pre if passing else (1 - pr_pre)
    script_adj = (opp_rate_rem / opp_rate_pre) if opp_rate_pre > 0 else 1.0
    # remaining opportunities as a share of the game's expected total: (1 − f) in plays, times the script multiplier.
    # (Using the pre-game plays_pg as the denominator instead was worse in the 2025 replay: its play-count unit does not
    # match a live box score's, so it biased Q1 projections low.)
    remaining_share = (1.0 - f) * script_adj
    # usage: live share vs projected share, shrunk toward the projection with few team opportunities
    usage_adj = 1.0
    if market == "player_pass_yds" and team_opps_so_far >= 8 and player_opps_so_far == 0:
        usage_adj = 0.0          # a QB with zero dropbacks after 8 team dropbacks is not playing (benched / injured)
    elif share_pre and share_pre > 0 and team_opps_so_far > 0:
        share_live = player_opps_so_far / team_opps_so_far
        k = usage_shrink if market != "player_pass_yds" else usage_shrink / 3   # a QB's share is ~binary: converge faster
        w = team_opps_so_far / (team_opps_so_far + k)
        usage_adj = (w * share_live + (1 - w) * share_pre) / share_pre
        usage_adj = min(max(usage_adj, 0.0), 3.0)
    mean_live = y_t + mean_pre * usage_adj * remaining_share
    sd_live = max(sd_pre * max(remaining_share, 0.0) ** SD_EXP.get(market, 0.5), sd_pre * sd_floor)
    return LiveProjection(mean_live=mean_live, sd_live=sd_live, f=f, usage_adj=usage_adj, script_adj=script_adj,
                          remaining_share=remaining_share)


def naive_pace(y_t: float, f: float) -> float:
    return y_t / f if f > 0.05 else float("nan")


def clock_to_seconds(period: int, display_clock: str) -> tuple[float, float]:
    """(seconds elapsed, seconds remaining) in regulation from ESPN's period + 'MM:SS' clock."""
    try:
        m, s = display_clock.split(":")
        left = int(m) * 60 + float(s)
    except Exception:
        left = 0.0
    if period <= 0:
        return 0.0, 3600.0
    if period > 4:            # overtime: treat as end of regulation plus a little
        return 3600.0, max(0.0, left)
    remaining = (4 - period) * 900 + left
    return 3600.0 - remaining, remaining
