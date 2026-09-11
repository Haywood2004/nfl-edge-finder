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


# ---------------------------------------------------------------- scoreboard + box score (same-day grading)
# Same site API as the live bot (live/live/espn.py); datacenter IPs get 403 from some hosts, so try each in turn.
HOSTS = [
    "https://site.api.espn.com/apis/site/v2/sports/football/nfl",
    "https://site.web.api.espn.com/apis/site/v2/sports/football/nfl",
    "https://cdn.espn.com/core/nfl",
]
_HDR = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*", "Accept-Language": "en-US,en;q=0.9", "Referer": "https://www.espn.com/"}


def _abbr(a):
    return ESPN_ABBR.get(a, a) if a else None


def _get(path: str, params: dict, kind: str) -> dict | None:
    errors = []
    for base in HOSTS:
        p = dict(params)
        if "cdn.espn.com" in base:
            p["xhr"] = 1
        try:
            r = requests.get(f"{base}{path}", params=p, headers=_HDR, timeout=20)
            r.raise_for_status()
            j = r.json()
            if isinstance(j, dict) and isinstance(j.get("content"), dict):
                c = j["content"]
                j = c.get("sbData", j) if kind == "scoreboard" else c.get("gamepackageJSON", j)
            return j
        except Exception as e:
            errors.append(f"{base.split('/')[2]}: {e}")
    print(f"[espn] {path} failed on every host: " + " | ".join(errors))
    return None


def fetch_scoreboard(date_yyyymmdd: str) -> list[dict]:
    j = _get("/scoreboard", {"dates": date_yyyymmdd}, "scoreboard")
    out = []
    for e in (j or {}).get("events", []) or []:
        c = (e.get("competitions") or [{}])[0]
        st = c.get("status") or e.get("status") or {}
        teams = {}
        for x in c.get("competitors", []) or []:
            teams[x.get("homeAway")] = {"abbr": _abbr((x.get("team") or {}).get("abbreviation")), "score": _to_int(x.get("score"))}
        out.append({"espn_id": str(e.get("id")), "state": ((st.get("type") or {}).get("state")) or "pre",
                    "home": teams.get("home", {}).get("abbr"), "away": teams.get("away", {}).get("abbr"),
                    "home_score": teams.get("home", {}).get("score"), "away_score": teams.get("away", {}).get("score")})
    return out


def fetch_summary(espn_id: str) -> dict | None:
    """→ {'players': {espn_id: {name, team, pass_att, pass_cmp, pass_yds, rush_att, rush_yds, rec, tgt, rec_yds}}}"""
    j = _get("/summary", {"event": espn_id}, "summary")
    if not j:
        return None
    players: dict[str, dict] = {}
    for t in (j.get("boxscore") or {}).get("players", []) or []:
        a = _abbr((t.get("team") or {}).get("abbreviation"))
        for cat in t.get("statistics", []) or []:
            name, keys = cat.get("name"), cat.get("keys") or []
            for ath in cat.get("athletes", []) or []:
                info = ath.get("athlete") or {}
                pid = str(info.get("id"))
                p = players.setdefault(pid, {"name": info.get("displayName"), "team": a, "pass_att": 0, "pass_cmp": 0, "pass_yds": 0.0,
                                             "rush_att": 0, "rush_yds": 0.0, "rec": 0, "tgt": 0, "rec_yds": 0.0})
                vals = dict(zip(keys, ath.get("stats") or []))
                if name == "passing":
                    ca = str(vals.get("completions/passingAttempts", "0/0")).split("/")
                    p["pass_cmp"], p["pass_att"] = _to_int(ca[0]) or 0, (_to_int(ca[1]) if len(ca) > 1 else 0) or 0
                    p["pass_yds"] = _to_float(vals.get("passingYards")) or 0.0
                elif name == "rushing":
                    p["rush_att"] = _to_int(vals.get("rushingAttempts")) or 0
                    p["rush_yds"] = _to_float(vals.get("rushingYards")) or 0.0
                elif name == "receiving":
                    p["rec"] = _to_int(vals.get("receptions")) or 0
                    p["tgt"] = _to_int(vals.get("receivingTargets")) or 0
                    p["rec_yds"] = _to_float(vals.get("receivingYards")) or 0.0
    return {"players": players}


def _to_int(v):
    try:
        return int(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _to_float(v):
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None
