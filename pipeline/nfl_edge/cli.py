"""python -m nfl_edge <job> [options]"""
from __future__ import annotations
import argparse
import warnings
warnings.filterwarnings("ignore", category=FutureWarning)
import sys


def main(argv=None):
    p = argparse.ArgumentParser(prog="nfl_edge")
    p.add_argument("job")
    p.add_argument("--seasons", type=int, nargs="*")
    p.add_argument("--week", type=int)
    p.add_argument("--label", default="manual")
    p.add_argument("--from-dir", help="replay recorded Odds API payloads from this directory")
    p.add_argument("--markets", nargs="*", default=["player_pass_yds"])
    p.add_argument("--max-events", type=int)
    a = p.parse_args(argv)

    from . import ingest
    if a.job == "ingest_schedule":
        ingest.ingest_schedule(a.seasons)
    elif a.job == "ingest_pbp":
        ingest.ingest_pbp(a.seasons)
    elif a.job == "ingest_weekly_stats":
        ingest.ingest_weekly_stats(a.seasons)
    elif a.job == "ingest_injuries":
        ingest.ingest_injuries(a.seasons)
    elif a.job == "backtest_lines":   # passing-yards model vs real closing lines (fixtures from odds_history)
        from .models.backtest_lines import run
        run(a.seasons or None)
    elif a.job == "odds_history":   # historical closing lines for backtests (costs credits; see odds_history.py)
        from .ingest.odds_history import backfill_odds_history
        backfill_odds_history(a.seasons or [2024, 2025], tuple(a.markets), max_events=a.max_events)
    elif a.job == "ingest_injuries_espn":
        ingest.ingest_injuries_espn()
    elif a.job == "ingest_depth_charts":
        ingest.ingest_depth_charts(a.seasons)
    elif a.job == "ingest_rosters":
        ingest.ingest_rosters(a.seasons)
    elif a.job == "ingest_snaps":
        ingest.ingest_snaps(a.seasons)
    elif a.job == "ingest_weather":
        ingest.ingest_weather(a.week)
    elif a.job == "ingest_odds":
        ingest.ingest_odds(a.label, tuple(a.markets), week=a.week, from_dir=a.from_dir, max_events=a.max_events)
    elif a.job == "snapshot":     # cron: new odds snapshot, then rescore both markets against it
        ingest.ingest_odds(a.label, tuple(a.markets), week=a.week, from_dir=a.from_dir, max_events=a.max_events)
        from .scoring.cards import score_week
        from .scoring.moneyline_cards import score_moneylines
        score_week(a.week); score_moneylines(a.week)
    elif a.job == "build_features":
        from .features.build import build_features
        build_features(a.seasons, a.week)
    elif a.job == "train":
        from .models.passing_yards import train
        train()
    elif a.job == "score":
        from .scoring.cards import score_week
        from .scoring.moneyline_cards import score_moneylines
        score_week(a.week); score_moneylines(a.week)
    elif a.job == "train_ml":
        from .models.moneyline import train
        train()
    elif a.job == "score_ml":
        from .scoring.moneyline_cards import score_moneylines
        score_moneylines(a.week)
    elif a.job == "grade":
        from .grading.grade import grade_cards
        grade_cards()
    elif a.job == "ingest_nflverse":
        ingest.ingest_schedule(); ingest.ingest_pbp(a.seasons); ingest.ingest_weekly_stats(a.seasons)
        ingest.ingest_injuries(); ingest.ingest_rosters(); ingest.ingest_injuries_espn(); ingest.ingest_depth_charts(); ingest.ingest_snaps()
    elif a.job == "weekly":       # Tuesday: refresh data, snapshot open, features, score
        ingest.ingest_schedule(list(range(2009, _cur() + 1))); ingest.ingest_pbp([_cur()]); ingest.ingest_weekly_stats([_cur()])
        # full injury history (2016+) is a model input (v2); idempotent, ~55k rows
        ingest.ingest_injuries(list(range(2016, _cur() + 1))); ingest.ingest_rosters(); ingest.ingest_injuries_espn()
        ingest.ingest_depth_charts(); ingest.ingest_snaps()
        ingest.ingest_odds("tue_open", tuple(a.markets))
        ingest.ingest_weather()
        from .features.build import build_features
        from .scoring.cards import score_week
        from .scoring.moneyline_cards import score_moneylines
        from .models.moneyline import train as train_ml
        from .models.passing_yards import train as train_py
        build_features(); train_ml(); train_py(); score_week(); score_moneylines()
    elif a.job == "gameday_am":   # Sunday 9am: injuries, weather, snapshot, rescore
        ingest.ingest_injuries(); ingest.ingest_injuries_espn(); ingest.ingest_depth_charts(); ingest.ingest_weather()
        ingest.ingest_odds("sun_am", tuple(a.markets))
        from .features.build import build_features
        from .scoring.cards import score_week
        from .scoring.moneyline_cards import score_moneylines
        build_features(); score_week(); score_moneylines()
    elif a.job == "bootstrap":    # first run from scratch
        ingest.ingest_schedule(list(range(2009, _cur() + 1))); ingest.ingest_pbp(); ingest.ingest_weekly_stats()
        ingest.ingest_injuries(); ingest.ingest_rosters(); ingest.ingest_injuries_espn(); ingest.ingest_depth_charts(); ingest.ingest_snaps()
        from .features.build import build_features
        from .models.passing_yards import train
        from .scoring.cards import score_week
        from .scoring.moneyline_cards import score_moneylines
        from .models.moneyline import train as train_ml
        build_features(); train(); train_ml()
        ingest.ingest_odds("tue_open", tuple(a.markets)); ingest.ingest_weather()
        score_week(); score_moneylines()
    else:
        print(f"unknown job {a.job}", file=sys.stderr); return 2
    return 0


def _cur():
    from .ingest.nflverse_jobs import current_season
    return current_season()


if __name__ == "__main__":
    sys.exit(main())
