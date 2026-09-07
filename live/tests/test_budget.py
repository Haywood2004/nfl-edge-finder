from live import config as C
from live.odds import Budget


def _b(live_spent=0, last_hour=0, key_remaining=15000, hours_left=240):
    b = Budget.__new__(Budget)
    b.live_spent, b.live_last_hour, b.key_remaining, b.hours_left = live_spent, last_hour, key_remaining, hours_left
    b.live_remaining = max(C.LIVE_CREDIT_BUDGET - live_spent, 0)
    b.hourly_allowance = b.live_remaining / hours_left
    return b


def test_plan_stop_at_85pct():
    ok, why = _b(key_remaining=int(C.ODDS_MONTHLY * 0.16)).can_spend(1)
    assert ok
    ok, why = _b(key_remaining=int(C.ODDS_MONTHLY * 0.14)).can_spend(1)
    assert not ok and "85%" in why


def test_live_budget_and_pacing():
    assert not _b(live_spent=C.LIVE_CREDIT_BUDGET).can_spend(1)[0]
    b = _b(live_spent=0, hours_left=100)            # allowance = budget/100 per hour
    assert b.can_spend(1)[0]
    b.live_last_hour = int(b.hourly_allowance * C.PACING_BURST) + 5
    ok, why = b.can_spend(1)
    assert not ok and why.startswith("pacing")


def test_record_updates():
    b = _b()
    b.record(3, 14000)
    assert b.live_spent == 3 and b.live_last_hour == 3 and b.key_remaining == 14000
