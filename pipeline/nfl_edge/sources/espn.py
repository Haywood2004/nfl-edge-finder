"""ESPN public injuries endpoint (undocumented, no key). See docs/DATA_SOURCES.md.

GET https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries
  → {"injuries": [{"displayName": "Arizona Cardinals", "injuries": [{"status": "Questionable", "date": ...,
       "athlete": {"id": "4870808", "displayName": ..., "position": {"abbreviation": "RB"},
                   "team": {"abbreviation": "ARI"}}, "details": {"type": "Ankle", ...}}, ...]}, ...]}
Statuses seen: Out, Doubtful, Questionable, Injured Reserve, Day-To-Day, Suspension, PUP.
"""
from __future__ import annotations
import requests

URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries"
STATUS_MAP = {"out": "Out", "doubtful": "Doubtful", "questionable": "Questionable",
              "injured reserve": "Out", "injured reserve - designated to return": "Out",
              "suspension": "Out", "physically unable to perform": "Out", "non-football injury": "Out",
              "day-to-day": "Questionable"}
ESPN_ABBR = {"WSH": "WAS", "LAR": "LA", "JAX": "JAX"}


def fetch_injuries(timeout: int = 30) -> list[dict]:
    r = requests.get(URL, timeout=timeout, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36", "Accept": "application/json"})
    r.raise_for_status()
    return parse_injuries(r.json())


def parse_injuries(payload: dict) -> list[dict]:
    out = []
    for team in payload.get("injuries", []):
        for inj in team.get("injuries", []):
            a = inj.get("athlete") or {}
            abbr = ((a.get("team") or {}).get("abbreviation")) or ""
            status_raw = (inj.get("status") or "").strip()
            status = STATUS_MAP.get(status_raw.lower(), status_raw or None)
            out.append({
                "espn_id": str(a.get("id")) if a.get("id") is not None else None,
                "full_name": a.get("displayName"),
                "position": ((a.get("position") or {}).get("abbreviation")),
                "team": ESPN_ABBR.get(abbr, abbr),
                "report_status": status,
                "report_primary_injury": ((inj.get("details") or {}).get("type")),
                "espn_status_raw": status_raw,
                "date": inj.get("date"),
            })
    return out
