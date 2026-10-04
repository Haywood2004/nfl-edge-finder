"""L3 Defense vs. Line experiment: rules, point-in-time, shrinkage, stats (no DB needed)."""
import numpy as np
import pandas as pd
import pytest
from nfl_edge.experimental import l3


def _play(gid, season, week, off, de, **kw):
    base = dict(game_id=gid, season=season, week=week, season_type="REG", posteam=off, defteam=de, play_type="pass",
                **{"pass": 1}, rush=0, qb_dropback=1, qb_scramble=0, sack=0, yards_gained=0, passing_yards=0,
                rushing_yards=0, epa=0.0, success=0)
    base.update(kw)
    return base


def _pbp(n_weeks=4, teams=("AAA", "BBB", "CCC", "DDD"), seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for season in (2024, 2025):
        for w in range(1, n_weeks + 1):
            ts = list(teams)
            rng.shuffle(ts)
            for i in range(0, len(ts), 2):
                a, b = ts[i], ts[i + 1]
                gid = f"{season}_{w:02d}_{a}_{b}"
                for off, de in ((a, b), (b, a)):
                    for _ in range(30):
                        y = int(rng.integers(0, 15))
                        rows.append(_play(gid, season, w, off, de, yards_gained=y, passing_yards=y, epa=rng.normal(), success=int(y > 5)))
                    rows.append(_play(gid, season, w, off, de, sack=1, yards_gained=-7, passing_yards=None))
                    for _ in range(20):
                        y = int(rng.integers(-2, 9))
                        rows.append(_play(gid, season, w, off, de, play_type="run", **{"pass": 0}, rush=1, qb_dropback=0,
                                          yards_gained=y, rushing_yards=y, epa=rng.normal() * 0.5, success=int(y > 3)))
                    rows.append(_play(gid, season, w, off, de, play_type="run", **{"pass": 0}, rush=1, qb_scramble=1,
                                      yards_gained=12, rushing_yards=12))
    return pd.DataFrame(rows)


def test_team_games_matches_teamrankings_definitions():
    p = _pbp()
    tg = l3.team_games(p)
    g = tg.iloc[0]
    sub = p[(p.game_id == g.game_id) & (p.defteam == g.defteam)]
    net_pass = sub.passing_yards.fillna(0).sum() + sub[sub.sack == 1].yards_gained.sum()
    assert g.pass_yds_tr == pytest.approx(net_pass)                        # net of sacks
    assert g.rush_yds_tr == pytest.approx(sub.rushing_yards.sum())          # includes the scramble
    assert g.carries_d == 20                                                # designed runs exclude the scramble
    assert g.dropbacks == 31                                                # attempts + sacks, no scrambles


def test_defense_table_is_point_in_time():
    tg = l3.team_games(_pbp())
    a = l3.defense_table(tg, 2025, 3)
    future = tg.copy()
    future.loc[(future.season == 2025) & (future.week >= 3), "pass_yds_net"] *= 10   # tamper with week ≥ 3
    b = l3.defense_table(future, 2025, 3)
    pd.testing.assert_frame_equal(a, b)
    assert (a.games <= 2).all() and (a.l3_games <= 2).all()


def test_shrinkage_bounds_and_sample_size():
    tg = l3.team_games(_pbp(n_weeks=5))
    t = l3.defense_table(tg, 2025, 6)
    for s in l3.STATS:
        assert t[f"{s}_shrink"].between(0, 1).all()
        assert (t[f"{s}_shrunk"].abs() <= t[f"{s}_adj"].abs() + t[f"{s}_prior"].abs() + 1e-9).all()
    params = {k: dict(v) for k, v in l3.DEFAULT_PARAMS.items()}
    params["pass_ypd"]["tau2"] = 100.0       # huge true-talent variance → trust the sample
    t2 = l3.defense_table(tg, 2025, 6, params)
    assert (t2.pass_ypd_shrink > 0.9).all()


def test_naive_conditions_use_preregistered_ranks():
    teams = [f"T{i:02d}" for i in range(32)]
    tg = l3.team_games(_pbp(n_weeks=3, teams=tuple(teams)))
    t = l3.defense_table(tg, 2025, 4)
    assert set(t.pass_naive_cond) <= {"soft", "stingy", ""}
    assert (t[t.pass_naive_cond == "soft"].pass_naive_rank >= l3.NAIVE_SOFT_MIN_RANK).all()
    assert (t[t.pass_naive_cond == "stingy"].pass_naive_rank <= l3.NAIVE_STINGY_MAX_RANK).all()
    t2 = l3.defense_table(tg, 2025, 3)       # only 2 games played → the last-3 rule cannot fire
    assert (t2.pass_naive_cond == "").all()


def test_naive_verdict():
    assert l3.naive_verdict(240.5, 313.0, 3, "soft") == "Over"
    assert l3.naive_verdict(222.5, 220.3, 3, "stingy") == "Under"
    assert l3.naive_verdict(246.5, 290.7, 3, "stingy") is None      # signals disagree → no flag
    assert l3.naive_verdict(219.5, 203.7, 3, "soft") is None
    assert l3.naive_verdict(200.5, 54.0, 1, "stingy") is None       # fewer than 3 games


def test_v1_verdict_needs_condition_and_edge():
    assert l3.v1_verdict(0.60, 0.52, "soft")[0] == "Over"
    assert l3.v1_verdict(0.53, 0.52, "soft")[0] is None              # agrees, but under the 3% bar
    assert l3.v1_verdict(0.40, 0.50, "stingy")[0] == "Under"
    assert l3.v1_verdict(0.70, 0.50, "")[0] is None                  # no defense condition → never flags


def test_projector_p_over_monotone():
    rng = np.random.default_rng(1)
    n = 400
    rows = pd.DataFrame({"season": 2024, "rate_l3": rng.normal(7, 1, n), "rate_season": rng.normal(7, 1, n),
                         "rate_prev": rng.normal(7, 1, n), "def_dev": rng.normal(0, .5, n), "wind_hi": False, "dome": False,
                         "vol_l3": rng.normal(33, 4, n), "vol_season": rng.normal(33, 4, n), "implied": rng.normal(22, 3, n),
                         "team_spread": rng.normal(0, 5, n), "actual_vol": rng.integers(20, 45, n)})
    rows["actual_yds"] = rows.actual_vol * rng.normal(7, 1.5, n)
    pj = l3.Projector(l3.PASS_MKT).fit(rows, l3.MARKETS[l3.PASS_MKT])
    p = pj.p_over(np.full(5, 230.0), np.array([150, 200, 230, 260, 320]))
    assert np.all(np.diff(p) <= 1e-12) and p[0] > 0.8 and p[-1] < 0.2
    rt = l3.Projector.from_json(pj.to_json())
    assert rt.project(rows.head(3)).tolist() == pytest.approx(pj.project(rows.head(3)).tolist())


def test_summarize_and_publishing_rule():
    b = pd.DataFrame({"result": ["win"] * 90 + ["loss"] * 70, "pnl": [0.91] * 90 + [-1.0] * 70})
    s = l3.summarize_bets(b)
    assert (s["w"], s["l"], s["n"]) == (90, 70, 160)
    assert s["ci_lo"] < s["roi"] < s["ci_hi"]
    assert l3.lean_eligible(s) == (s["ci_lo"] > l3.LEAN_MIN_CI_LO)
    assert not l3.lean_eligible(l3.summarize_bets(b.head(100)))       # < 150 bets is never a lean


def test_parse_teamrankings():
    from nfl_edge.experimental.l3_jobs import parse_teamrankings
    html = """<table class="tr-table"><thead><tr><th>Rank</th><th>Team</th><th>2026</th><th>Last 3</th></tr></thead><tbody>
              <tr><td>1</td><td>Seattle</td><td>141.7</td><td>141.7</td><td>176.0</td></tr>
              <tr><td>2</td><td>LA Rams</td><td>171.3</td><td>170.0</td><td>179.0</td></tr></tbody></table>"""
    assert parse_teamrankings(html) == {"SEA": 141.7, "LA": 170.0}


def test_naive_g10_gate():
    assert l3.naive_g10_verdict(222.5, 220.3, 3, "stingy") is None      # Cousins: 1% gap fails the 10% gate
    assert l3.naive_g10_verdict(240.5, 313.0, 3, "soft") == "Over"      # Bryce Young: +30%
    assert l3.naive_g10_verdict(98.5, 102.3, 3, "soft") is None         # Gibbs: +3.9%
    assert l3.naive_g10_verdict(59.5, 71.3, 3, "soft") == "Over"        # Kyren Williams: +19.9%
    assert l3.naive_g10_verdict(246.5, 290.7, 3, "stingy") is None      # big gap but signals disagree
    assert l3.naive_gap(200.0, 220.0) == pytest.approx(0.10)
