import pytest
from live.ingame import project, expected_pass_rate_remaining, expected_remaining_plays, clock_to_seconds, NEUTRAL_PASS_RATE

BASE = dict(team_plays_pg=63.0, team_pass_rate=0.58, share_pre=0.25)


def _p(market="player_reception_yds", y_t=40.0, mean=70.0, sd=25.0, **kw):
    a = dict(plays_so_far=30, secs_elapsed=1800, secs_remaining=1800, score_diff=0, team_opps_so_far=18, player_opps_so_far=5, **BASE)
    a.update(kw)
    return project(market, y_t, mean, sd, **a)


def test_kickoff_equals_pregame():
    lp = _p(y_t=0.0, plays_so_far=0, secs_elapsed=0, secs_remaining=3600, team_opps_so_far=0, player_opps_so_far=0)
    assert lp.f == 0.0 and lp.usage_adj == 1.0
    assert lp.mean_live == pytest.approx(70.0, rel=0.03)      # neutral script ≈ pre-game
    assert lp.sd_live == pytest.approx(25.0, rel=0.03)


def test_final_whistle_is_the_stat():
    lp = _p(y_t=83.0, plays_so_far=62, secs_elapsed=3600, secs_remaining=0)
    assert lp.mean_live == pytest.approx(83.0)
    assert lp.sd_live == pytest.approx(25.0 * 0.20)         # floor (remaining_share = 0)


def test_usage_adjustment_direction():
    hot = _p(player_opps_so_far=9, team_opps_so_far=18)      # 50% target share vs 25% projected
    cold = _p(player_opps_so_far=1, team_opps_so_far=18)
    base = _p(player_opps_so_far=4.5, team_opps_so_far=18)
    assert hot.usage_adj > 1 > cold.usage_adj
    assert hot.mean_live > base.mean_live > cold.mean_live
    assert hot.usage_adj < 2.0                                # shrunk toward 1 with only 18 team dropbacks


def test_script_direction_passing_vs_rushing():
    trailing = _p(score_diff=-14, market="player_pass_yds", share_pre=1.0, y_t=150, mean=250, sd=60)
    leading = _p(score_diff=+14, market="player_pass_yds", share_pre=1.0, y_t=150, mean=250, sd=60)
    assert trailing.script_adj > 1 > leading.script_adj
    assert trailing.mean_live > leading.mean_live
    r_trail = _p(score_diff=-14, market="player_rush_yds", team_opps_so_far=12, player_opps_so_far=8, y_t=40, mean=70, sd=28)
    r_lead = _p(score_diff=+14, market="player_rush_yds", team_opps_so_far=12, player_opps_so_far=8, y_t=40, mean=70, sd=28)
    assert r_lead.mean_live > r_trail.mean_live


def test_benched_qb():
    lp = _p(market="player_pass_yds", share_pre=1.0, y_t=0, team_opps_so_far=12, player_opps_so_far=0, mean=240, sd=60)
    assert lp.usage_adj == 0.0 and lp.mean_live == 0.0


def test_pass_rate_table_and_pace():
    assert expected_pass_rate_remaining(3600, 0) == pytest.approx(NEUTRAL_PASS_RATE, abs=0.05)
    assert expected_pass_rate_remaining(300, -10) > 0.8 > expected_pass_rate_remaining(300, +10)
    assert expected_remaining_plays(0, 0, 3600, 63.0) == pytest.approx(63.0)
    fast = expected_remaining_plays(40, 1800, 1800, 63.0)     # 40 plays in a half: faster than 63/game
    assert fast > 31.5


def test_clock():
    assert clock_to_seconds(1, "15:00") == (0.0, 3600.0)
    assert clock_to_seconds(3, "8:32") == (3600 - (900 + 512), 900 + 512)
    assert clock_to_seconds(4, "0:00") == (3600.0, 0.0)
    assert clock_to_seconds(2, "garbage")[1] == 1800.0
