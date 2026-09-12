"""Team ratings for the moneyline model — point-in-time by construction.

Elo (FiveThirtyEight-style): K=20, home field 48 pts, margin-of-victory multiplier, 1/3 regression to
1500 between seasons. Computed sequentially over every game since 2009 so each game's pre-game
ratings only reflect games already played.

QB continuity: `qb_change` = the listed starter (raw_games.*_qb_id) differs from the team's starter
in its previous game; `qb_starts` = that QB's prior starts for any team (small → uncertainty).

EPA ratings come from feat_team_offense / feat_team_defense (already point-in-time per week).
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from .. import db

K = 20.0
HFA = 48.0
SEASON_REGRESS = 1 / 3


def _expected(diff: float) -> float:
    return 1 / (1 + 10 ** (-diff / 400))


def elo_history(games: pd.DataFrame) -> pd.DataFrame:
    """games: raw_games rows (all types) sorted by kickoff. Returns per game: elo_home_pre, elo_away_pre."""
    elo: dict[str, float] = {}
    last_season: dict[str, int] = {}
    qb_last: dict[str, str] = {}
    qb_starts: dict[str, int] = {}
    out = []
    for g in games.itertuples(index=False):
        for t in (g.home_team, g.away_team):
            elo.setdefault(t, 1500.0)
            if last_season.get(t) is not None and g.season > last_season[t]:
                elo[t] = 1500 + (elo[t] - 1500) * (1 - SEASON_REGRESS)
            last_season[t] = g.season
        h, a = elo[g.home_team], elo[g.away_team]
        hq, aq = g.home_qb_id, g.away_qb_id
        rec = {"game_id": g.game_id, "elo_home_pre": h, "elo_away_pre": a,
               "home_qb_change": int(bool(hq) and qb_last.get(g.home_team) not in (None, hq)),
               "away_qb_change": int(bool(aq) and qb_last.get(g.away_team) not in (None, aq)),
               "home_qb_starts": qb_starts.get(hq, 0) if hq else np.nan,
               "away_qb_starts": qb_starts.get(aq, 0) if aq else np.nan}
        out.append(rec)
        if pd.isna(g.home_score) or pd.isna(g.away_score):
            continue  # future game: ratings unchanged
        diff = (h + (0 if g.location == "Neutral" else HFA)) - a
        exp_home = _expected(diff)
        margin = g.home_score - g.away_score
        result = 1.0 if margin > 0 else 0.0 if margin < 0 else 0.5
        winner_diff = diff if margin > 0 else -diff
        mov = np.log(abs(margin) + 1) * (2.2 / (winner_diff * 0.001 + 2.2)) if margin != 0 else 1.0
        delta = K * mov * (result - exp_home)
        elo[g.home_team] = h + delta
        elo[g.away_team] = a - delta
        if hq:
            qb_last[g.home_team] = hq; qb_starts[hq] = qb_starts.get(hq, 0) + 1
        if aq:
            qb_last[g.away_team] = aq; qb_starts[aq] = qb_starts.get(aq, 0) + 1
    return pd.DataFrame(out)


def game_features(seasons: list[int]) -> pd.DataFrame:
    """One row per REG game (home perspective) with pre-game Elo, EPA ratings, rest, context, and result."""
    games = db.read_sql("SELECT * FROM raw_games WHERE kickoff_utc IS NOT NULL ORDER BY kickoff_utc, game_id")
    # future games have no listed QB yet → use the current depth-chart QB1 so qb_change is meaningful
    fut = games.home_score.isna()
    if fut.any():
        from .players import current_qb1
        import datetime as dt
        qb1 = current_qb1(int(games[fut].season.max()), dt.datetime.now(dt.timezone.utc))
        q = dict(zip(qb1.team, qb1.player_id))
        games.loc[fut & games.home_qb_id.isna(), "home_qb_id"] = games.loc[fut, "home_team"].map(q)
        games.loc[fut & games.away_qb_id.isna(), "away_qb_id"] = games.loc[fut, "away_team"].map(q)
    hist = elo_history(games)
    g = games.merge(hist, on="game_id")
    g = g[(g.game_type == "REG") & g.season.isin(seasons)].copy()
    off = db.read_sql("SELECT season, week, team, epa_per_play, pass_epa_per_db, games FROM feat_team_offense")
    dfe = db.read_sql("SELECT season, week, team, pass_epa_allowed, rush_epa_allowed, games FROM feat_team_defense")
    for side in ("home", "away"):
        g = g.merge(off.rename(columns={"team": f"{side}_team", "epa_per_play": f"{side}_off_epa",
                                        "pass_epa_per_db": f"{side}_off_pass_epa", "games": f"{side}_games"}),
                    on=["season", "week", f"{side}_team"], how="left")
        g = g.merge(dfe.rename(columns={"team": f"{side}_team", "pass_epa_allowed": f"{side}_def_pass_epa",
                                        "rush_epa_allowed": f"{side}_def_rush_epa", "games": f"{side}_dgames"}),
                    on=["season", "week", f"{side}_team"], how="left")
    f = pd.DataFrame({
        "game_id": g.game_id, "season": g.season, "week": g.week, "kickoff_utc": g.kickoff_utc,
        "home_team": g.home_team, "away_team": g.away_team,
        "elo_diff": g.elo_home_pre - g.elo_away_pre,
        "elo_home": g.elo_home_pre, "elo_away": g.elo_away_pre,
        "epa_diff": (g.home_off_epa.fillna(0) - g.home_def_pass_epa.fillna(0) * 0.6 - g.home_def_rush_epa.fillna(0) * 0.4)
                    - (g.away_off_epa.fillna(0) - g.away_def_pass_epa.fillna(0) * 0.6 - g.away_def_rush_epa.fillna(0) * 0.4),
        "home_off_epa": g.home_off_epa, "away_off_epa": g.away_off_epa,
        "home_def_epa": g.home_def_pass_epa * 0.6 + g.home_def_rush_epa * 0.4,
        "away_def_epa": g.away_def_pass_epa * 0.6 + g.away_def_rush_epa * 0.4,
        "rest_diff": (g.home_rest.fillna(7) - g.away_rest.fillna(7)).clip(-10, 10),
        "home_rest": g.home_rest, "away_rest": g.away_rest,
        "div_game": g.div_game.fillna(0), "neutral": (g.location == "Neutral").astype(int),
        "home_qb_change": g.home_qb_change, "away_qb_change": g.away_qb_change,
        "home_qb_starts": g.home_qb_starts, "away_qb_starts": g.away_qb_starts,
        "week_num": g.week, "home_games": g.home_games, "away_games": g.away_games,
        "spread_line": g.spread_line, "total_line": g.total_line, "home_ml": g.home_moneyline, "away_ml": g.away_moneyline,
        "home_score": g.home_score, "away_score": g.away_score,
    })
    f["home_win"] = np.where(f.home_score.isna(), np.nan, (f.home_score > f.away_score).astype(float))
    f["qb_change_diff"] = f.home_qb_change.fillna(0) - f.away_qb_change.fillna(0)
    f["qb_inexp_diff"] = (np.log1p(f.home_qb_starts.fillna(0)) - np.log1p(f.away_qb_starts.fillna(0)))
    return f
