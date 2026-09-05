"""Historical closing lines from The Odds API (historical endpoints) for backtesting.

For every REG-season game in the requested seasons, fetch the per-event prop odds as of
(kickoff − CLOSE_MINUTES) — the closing line — and store them exactly like a live snapshot:
odds_snapshots(label='hist_close', source='historical', season, week) → odds_lines, plus a
compact parquet fixture per season in pipeline/fixtures/odds_history/ so the model backtest can
run anywhere without touching the API again.

Cost: historical event odds = 10 credits per market per region per event; historical events list
= 1 credit. One season of one prop market ≈ 272 × 10 = 2,720 credits. The job stops cleanly when
x-requests-remaining drops below CREDIT_RESERVE so the in-season snapshot schedule keeps working.
Idempotent: games that already have hist_close lines for the market are skipped.
"""
from __future__ import annotations
import datetime as dt
from pathlib import Path
import pandas as pd
from .. import db
from ..config import ROOT
from ..sources.odds_api import OddsAPI, SPORT
from ..teams import ODDS_API_TO_ABBR
from .odds_jobs import _lines_from_bookmakers, build_consensus

CLOSE_MINUTES = 60
CREDIT_RESERVE = 3000   # keep enough for the in-season snapshot schedule (4 prop markets ≈ 400 credits/week)
FIXTURE_DIR = ROOT / "pipeline" / "fixtures" / "odds_history"


def _hist_get(api: OddsAPI, path: str, params: dict, note: str, tries: int = 4) -> dict:
    """Historical calls are long-running batches; retry transient connection errors with backoff."""
    import time, requests
    for i in range(tries):
        try:
            return api._get(path, params, note)
        except (requests.ConnectionError, requests.Timeout) as e:
            if i == tries - 1:
                raise
            print(f"[hist] transient error ({e.__class__.__name__}), retry {i + 1}/{tries - 1}")
            time.sleep(3 * (i + 1))


def _week_events(api: OddsAPI, season: int, week: int, games: pd.DataFrame) -> pd.DataFrame:
    """Historical events list as of 36h before the week's first kickoff, mapped to raw_games."""
    first = games.kickoff_utc.min() - pd.Timedelta(hours=36)
    payload = _hist_get(api, f"/historical/sports/{SPORT}/events", {"date": first.strftime("%Y-%m-%dT%H:%M:%SZ")},
                        f"hist_events:{season}w{week}")
    ev = pd.DataFrame(payload.get("data", []))
    if ev.empty:
        return ev
    ev["home_abbr"] = ev.home_team.map(ODDS_API_TO_ABBR)
    ev["away_abbr"] = ev.away_team.map(ODDS_API_TO_ABBR)
    ev["commence_time"] = pd.to_datetime(ev.commence_time, utc=True)
    m = ev.merge(games, left_on=["home_abbr", "away_abbr"], right_on=["home_team", "away_team"], how="inner", suffixes=("", "_g"))
    m["dh"] = (m.commence_time - m.kickoff_utc).abs().dt.total_seconds() / 3600
    m = m[m.dh <= 36].sort_values("dh").drop_duplicates("game_id")
    return m.rename(columns={"id": "event_id"})[["event_id", "game_id", "commence_time", "home_team", "away_team",
                                                  "home_abbr", "away_abbr", "kickoff_utc"]]


def backfill_odds_history(seasons: list[int], markets: tuple[str, ...] = ("player_pass_yds",),
                          regions: str = "us", max_events: int | None = None) -> int:
    api = OddsAPI()
    total = 0
    with db.JobRun("odds_history") as run:
        for season in seasons:
            games = db.read_sql("""SELECT game_id, season, week, home_team, away_team, kickoff_utc FROM raw_games
                                   WHERE season=:s AND game_type='REG' AND home_score IS NOT NULL ORDER BY kickoff_utc""",
                                {"s": season})
            games["kickoff_utc"] = pd.to_datetime(games.kickoff_utc, utc=True)
            done = set(db.read_sql("""SELECT DISTINCT e.game_id FROM odds_lines l JOIN odds_snapshots s ON s.id=l.snapshot_id
                                      JOIN odds_events e ON e.event_id=l.event_id
                                      WHERE s.label='hist_close' AND s.season=:s AND l.market = ANY(:m)""",
                                   {"s": season, "m": list(markets)}).game_id)
            n_season = 0
            for week, wg in games.groupby("week"):
                todo = wg[~wg.game_id.isin(done)]
                if todo.empty:
                    continue
                remaining = api.last_headers.get("x-requests-remaining")
                if remaining is not None and int(remaining) < CREDIT_RESERVE:
                    print(f"[hist] stopping: {remaining} credits left (< reserve {CREDIT_RESERVE})")
                    run.detail["stopped"] = f"{season} wk{week}"
                    break
                ev = _week_events(api, season, int(week), todo)
                if ev.empty:
                    print(f"[hist] {season} wk{week}: no events found"); continue
                db.upsert(ev.drop(columns=["kickoff_utc"]), "odds_events", ["event_id"])
                snap_id = db.insert_returning_id("odds_snapshots", {
                    "label": "hist_close", "season": season, "week": int(week), "markets": list(markets),
                    "source": "historical", "taken_at": wg.kickoff_utc.max().to_pydatetime()})
                rows, credits = [], 0
                for _, e in ev.iterrows():
                    if max_events and n_season >= max_events:
                        break
                    at = (e.kickoff_utc - pd.Timedelta(minutes=CLOSE_MINUTES)).strftime("%Y-%m-%dT%H:%M:%SZ")
                    try:
                        eo = _hist_get(api, f"/historical/sports/{SPORT}/events/{e.event_id}/odds",
                                       {"date": at, "regions": regions, "markets": ",".join(markets), "oddsFormat": "decimal"},
                                       f"hist_event_odds:{e.game_id}")
                    except Exception as ex:  # a single missing event must not kill the backfill
                        print(f"[hist] {e.game_id}: {ex}"); continue
                    credits += int(api.last_headers.get("x-requests-last", 0) or 0)
                    data = eo.get("data") or {}
                    rows += _lines_from_bookmakers(e.event_id, data.get("bookmakers", []), snap_id)
                    n_season += 1
                if rows:
                    db.append(pd.DataFrame(rows), "odds_lines")
                    build_consensus(snap_id)
                db.execute("UPDATE odds_snapshots SET credits_used=:c WHERE id=:id", {"c": credits, "id": snap_id})
                total += len(rows)
                print(f"[hist] {season} wk{week}: {len(ev)} events, {len(rows)} lines, {credits} credits, "
                      f"{api.last_headers.get('x-requests-remaining')} remaining")
                write_fixture(season, markets)   # after every week so a crash still leaves a committed fixture
        run.rows = total
    return total


def write_fixture(season: int, markets: tuple[str, ...]) -> Path:
    """Flatten hist_close lines for a season into a parquet the backtest can load without the DB/API."""
    df = db.read_sql("""SELECT s.season, s.week, e.game_id, e.commence_time, l.market, l.bookmaker, l.player, l.side,
                               l.line, l.price_decimal, l.price_american, l.book_last_update
                        FROM odds_lines l JOIN odds_snapshots s ON s.id=l.snapshot_id JOIN odds_events e ON e.event_id=l.event_id
                        WHERE s.label='hist_close' AND s.season=:s""", {"s": season})   # ALL markets: one fixture per season
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    p = FIXTURE_DIR / f"{season}.parquet"
    df.to_parquet(p, index=False)
    print(f"[hist] fixture {p.name}: {len(df)} lines")
    return p


def load_fixtures(seasons: list[int] | None = None) -> pd.DataFrame:
    """Historical closing lines from the parquet fixtures (or the DB if a fixture is missing)."""
    frames = []
    for p in sorted(FIXTURE_DIR.glob("*.parquet")):
        s = int(p.stem)
        if seasons and s not in seasons:
            continue
        frames.append(pd.read_parquet(p))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
