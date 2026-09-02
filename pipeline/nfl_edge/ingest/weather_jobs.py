"""Open-Meteo forecast for each outdoor game of the target week (append-only).

Endpoint: https://api.open-meteo.com/v1/forecast?latitude&longitude&hourly=temperature_2m,wind_speed_10m,
          precipitation,precipitation_probability&temperature_unit=fahrenheit&wind_speed_unit=mph&timezone=UTC
Free, no key, ~10k req/day. Domes get a row with is_dome=true and no fetch.
A failed fetch is logged and skipped — the weather factor is then "unavailable" downstream (never fatal).
"""
from __future__ import annotations
import datetime as dt
import pandas as pd
import requests
from .. import db
from .odds_jobs import target_week

URL = "https://api.open-meteo.com/v1/forecast"


def ingest_weather(week: int | None = None) -> int:
    season, wk = target_week()
    wk = week or wk
    games = db.read_sql("""SELECT g.game_id, g.kickoff_utc, g.roof, g.home_team, s.lat, s.lon, s.roof AS s_roof
                           FROM raw_games g LEFT JOIN stadiums s ON s.team=g.home_team
                           WHERE g.season=:s AND g.week=:w""", {"s": season, "w": wk})
    rows, n_ok = [], 0
    with db.JobRun("ingest_weather") as run:
        for _, g in games.iterrows():
            roof = g.roof if isinstance(g.roof, str) else g.s_roof
            is_dome = roof in ("dome", "closed", "retractable")
            row = {"game_id": g.game_id, "is_dome": is_dome, "raw": None}
            if not is_dome and pd.notna(g.lat):
                try:
                    r = requests.get(URL, params={
                        "latitude": g.lat, "longitude": g.lon,
                        "hourly": "temperature_2m,wind_speed_10m,precipitation,precipitation_probability",
                        "temperature_unit": "fahrenheit", "wind_speed_unit": "mph", "timezone": "UTC",
                        "forecast_days": 16}, timeout=30)
                    r.raise_for_status()
                    j = r.json()
                    ko = pd.Timestamp(g.kickoff_utc).floor("h").strftime("%Y-%m-%dT%H:%M")
                    times = j["hourly"]["time"]
                    if ko in times:
                        i = times.index(ko)
                        h = j["hourly"]
                        row.update({"temp_f": h["temperature_2m"][i], "wind_mph": h["wind_speed_10m"][i],
                                    "precip_in": h["precipitation"][i],
                                    "precip_prob": h["precipitation_probability"][i]})
                        n_ok += 1
                    row["raw"] = {"kickoff_hour": ko, "found": ko in times}
                except Exception as e:  # graceful degradation
                    row["raw"] = {"error": repr(e)[:200]}
                    print(f"[weather] {g.game_id}: {e!r}")
            rows.append(row)
        run.rows = db.append(pd.DataFrame(rows), "raw_weather")
        run.detail = {"forecasts": n_ok, "games": len(games)}
        return run.rows
