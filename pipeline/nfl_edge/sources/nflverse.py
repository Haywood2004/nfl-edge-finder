"""nflverse data loader.

Reads release assets directly from github.com/nflverse/nflverse-data (the same files
nfl_data_py wraps). We bypass nfl_data_py because (a) its schedule loader points at a
third-party mirror and (b) it is deprecated in favour of nflreadpy. Files are cached in
CACHE_DIR and re-downloaded when older than `max_age_hours` (in-season data is rebuilt
nightly by nflverse).
"""
from __future__ import annotations
import time
from pathlib import Path
import pandas as pd
import requests
from ..config import CACHE_DIR

BASE = "https://github.com/nflverse/nflverse-data/releases/download"

ASSETS = {
    "schedules": lambda y: f"{BASE}/schedules/games.csv",
    "pbp": lambda y: f"{BASE}/pbp/play_by_play_{y}.parquet",
    "weekly_stats": lambda y: f"{BASE}/stats_player/stats_player_week_{y}.parquet",
    "injuries": lambda y: f"{BASE}/injuries/injuries_{y}.parquet",
    "depth_charts": lambda y: f"{BASE}/depth_charts/depth_charts_{y}.parquet",
    "snap_counts": lambda y: f"{BASE}/snap_counts/snap_counts_{y}.parquet",
    "rosters": lambda y: f"{BASE}/rosters/roster_{y}.parquet",
    "rosters_weekly": lambda y: f"{BASE}/weekly_rosters/roster_weekly_{y}.parquet",
    "ngs_passing": lambda y: f"{BASE}/nextgen_stats/ngs_{y}_passing.csv.gz",
}


class NotAvailable(Exception):
    """Asset does not exist yet (e.g. pbp for a season that hasn't started)."""


def _path(kind: str, season: int | None) -> Path:
    url = ASSETS[kind](season)
    return CACHE_DIR / url.rsplit("/", 1)[-1]


def fetch(kind: str, season: int | None = None, max_age_hours: float = 12) -> Path:
    url = ASSETS[kind](season)
    p = _path(kind, season)
    fresh = p.exists() and (time.time() - p.stat().st_mtime) < max_age_hours * 3600
    # completed seasons never change materially; keep forever
    if p.exists() and season is not None and season < pd.Timestamp.utcnow().year - 1:
        fresh = True
    if fresh:
        return p
    r = requests.get(url, timeout=300, stream=True)
    if r.status_code == 404:
        if p.exists():
            return p
        raise NotAvailable(f"{kind} {season} not published yet ({url})")
    r.raise_for_status()
    tmp = p.with_suffix(p.suffix + ".part")
    with open(tmp, "wb") as f:
        for chunk in r.iter_content(1 << 20):
            f.write(chunk)
    tmp.replace(p)
    return p


def load(kind: str, season: int | None = None, columns: list[str] | None = None, **kw) -> pd.DataFrame:
    p = fetch(kind, season, **kw)
    if p.suffix == ".parquet":
        return pd.read_parquet(p, columns=columns)
    if p.name.endswith(".csv.gz"):
        return pd.read_csv(p, compression="gzip", usecols=columns, low_memory=False)
    return pd.read_csv(p, usecols=columns, low_memory=False)
