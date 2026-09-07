"""ESPN public endpoints for live game state (undocumented, no key; docs/LIVE.md).

  scoreboard  site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard[?dates=YYYYMMDD]
              → events[].competitions[0]: status{period, displayClock, type{state: pre|in|post}},
                competitors[{team{abbreviation}, homeAway, score}], situation{possession, down, distance, ...}
  summary     .../summary?event=<id>
              → boxscore.players[team].statistics[{name: passing|rushing|receiving, keys[], athletes[{athlete{id, displayName}, stats[]}]}]
                boxscore.teams[i].statistics[{name: totalOffensivePlays|..., displayValue}]
Structure verified against the 2025 Week 1 payloads (ATL–TB). Everything is parsed defensively; a missing field
degrades to None, never an exception. Responses are cached CACHE_SEC seconds.
"""
from __future__ import annotations
import time
import requests
from nfl_edge.sources.espn import ESPN_ABBR

# ESPN serves the same site API from several hosts; datacenter IP ranges get 403 from some of them, so each call
# tries the hosts in order and remembers the first one that answers (docs/LIVE.md).
HOSTS = [
    "https://site.api.espn.com/apis/site/v2/sports/football/nfl",
    "https://site.web.api.espn.com/apis/site/v2/sports/football/nfl",
    "https://cdn.espn.com/core/nfl",          # ?xhr=1 form; scoreboard/summary payloads are wrapped (see _unwrap)
]
BASE = HOSTS[0]
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36",
           "Accept": "application/json, text/plain, */*", "Accept-Language": "en-US,en;q=0.9", "Referer": "https://www.espn.com/",
           "Origin": "https://www.espn.com"}
CACHE_SEC = 15


def _unwrap(j: dict, kind: str) -> dict:
    """cdn.espn.com wraps the same objects: scoreboard → content.sbData, summary → content.gamepackageJSON."""
    if isinstance(j, dict) and "content" in j and isinstance(j["content"], dict):
        c = j["content"]
        if kind == "scoreboard" and "sbData" in c:
            return c["sbData"]
        if kind == "summary" and "gamepackageJSON" in c:
            return c["gamepackageJSON"]
    return j


def abbr(a: str | None) -> str | None:
    return ESPN_ABBR.get(a, a) if a else None


class ESPN:
    def __init__(self, session: requests.Session | None = None):
        self.s = session or requests.Session()
        self.cache: dict[str, tuple[float, dict]] = {}
        self.host_idx = 0
        self.fail_streak = 0

    def _get(self, path: str, params: dict | None = None, kind: str = "scoreboard") -> dict | None:
        key = path + str(sorted((params or {}).items()))
        hit = self.cache.get(key)
        if hit and time.time() - hit[0] < CACHE_SEC:
            return hit[1]
        errors = []
        for i in range(len(HOSTS)):
            idx = (self.host_idx + i) % len(HOSTS)
            base = HOSTS[idx]
            p = dict(params or {})
            if "cdn.espn.com" in base:
                p["xhr"] = 1
            try:
                r = self.s.get(f"{base}{path}", params=p, headers=HEADERS, timeout=20)
                r.raise_for_status()
                j = _unwrap(r.json(), kind)
            except Exception as e:
                errors.append(f"{base.split('/')[2]}: {e}")
                continue
            if idx != self.host_idx:
                print(f"[espn] switched to {base.split('/')[2]}")
                self.host_idx = idx
            self.fail_streak = 0
            self.cache[key] = (time.time(), j)
            return j
        self.fail_streak += 1
        if self.fail_streak <= 3 or self.fail_streak % 30 == 0:     # do not spam the log every 20 s
            print(f"[espn] {path} failed on every host ({self.fail_streak}x): " + " | ".join(errors))
        return hit[1] if hit else None      # stale beats nothing

    def scoreboard(self, date: str | None = None) -> list[dict]:
        j = self._get("/scoreboard", {"dates": date} if date else None, kind="scoreboard")
        return parse_scoreboard(j) if j else []

    def summary(self, espn_id: str) -> dict | None:
        j = self._get("/summary", {"event": espn_id}, kind="summary")
        return parse_summary(j) if j else None


def parse_scoreboard(j: dict) -> list[dict]:
    out = []
    for e in j.get("events", []) or []:
        comps = e.get("competitions") or [{}]
        c = comps[0]
        st = c.get("status") or e.get("status") or {}
        teams = {}
        for x in c.get("competitors", []) or []:
            t = (x.get("team") or {}).get("abbreviation")
            teams[x.get("homeAway")] = {"abbr": abbr(t), "score": _int(x.get("score")), "id": (x.get("team") or {}).get("id")}
        sit = c.get("situation") or {}
        poss = sit.get("possession")
        poss_abbr = next((v["abbr"] for v in teams.values() if v.get("id") == poss), None)
        out.append({
            "espn_id": str(e.get("id")), "date": e.get("date"), "name": e.get("shortName"),
            "state": ((st.get("type") or {}).get("state")) or "pre",
            "period": _int(st.get("period")), "clock": st.get("displayClock"),
            "home": teams.get("home", {}).get("abbr"), "away": teams.get("away", {}).get("abbr"),
            "home_score": teams.get("home", {}).get("score"), "away_score": teams.get("away", {}).get("score"),
            "possession": poss_abbr, "down": sit.get("down"), "distance": sit.get("distance"),
            "detail": (st.get("type") or {}).get("detail"),
        })
    return out


def parse_summary(j: dict) -> dict:
    """→ {'teams': {ABBR: {'plays': int|None}}, 'players': {espn_id: {name, team, pass_att, pass_cmp, pass_yds, rush_att, rush_yds, rec, tgt, rec_yds}}}"""
    box = j.get("boxscore") or {}
    teams: dict[str, dict] = {}
    for t in box.get("teams", []) or []:
        a = abbr((t.get("team") or {}).get("abbreviation"))
        stats = {s.get("name"): s.get("displayValue") for s in t.get("statistics", []) or []}
        teams[a] = {"plays": _int(stats.get("totalOffensivePlays")), "pass_att": _slash(stats.get("completionAttempts"), 1),
                    "rush_att": _int(stats.get("rushingAttempts"))}
    players: dict[str, dict] = {}
    for t in box.get("players", []) or []:
        a = abbr((t.get("team") or {}).get("abbreviation"))
        for cat in t.get("statistics", []) or []:
            name = cat.get("name"); keys = cat.get("keys") or []
            for ath in cat.get("athletes", []) or []:
                info = ath.get("athlete") or {}
                pid = str(info.get("id"))
                p = players.setdefault(pid, {"espn_id": pid, "name": info.get("displayName"), "team": a,
                                             "pass_att": 0, "pass_cmp": 0, "pass_yds": 0.0, "rush_att": 0, "rush_yds": 0.0,
                                             "rec": 0, "tgt": 0, "rec_yds": 0.0})
                vals = dict(zip(keys, ath.get("stats") or []))
                if name == "passing":
                    ca = vals.get("completions/passingAttempts", "0/0")
                    p["pass_cmp"], p["pass_att"] = _slash(ca, 0) or 0, _slash(ca, 1) or 0
                    p["pass_yds"] = _float(vals.get("passingYards")) or 0.0
                elif name == "rushing":
                    p["rush_att"] = _int(vals.get("rushingAttempts")) or 0
                    p["rush_yds"] = _float(vals.get("rushingYards")) or 0.0
                elif name == "receiving":
                    p["rec"] = _int(vals.get("receptions")) or 0
                    p["tgt"] = _int(vals.get("receivingTargets")) or 0
                    p["rec_yds"] = _float(vals.get("receivingYards")) or 0.0
    # team dropbacks ≈ pass attempts + sacks; sacks are per-QB "sacks-sackYardsLost" — approximate with attempts
    for a, t in teams.items():
        if t.get("pass_att") is None:
            t["pass_att"] = sum(p["pass_att"] for p in players.values() if p["team"] == a)
        if t.get("rush_att") is None:
            t["rush_att"] = sum(p["rush_att"] for p in players.values() if p["team"] == a)
    return {"teams": teams, "players": players}


def _int(v):
    try:
        return int(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _float(v):
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _slash(v, i):
    try:
        return int(str(v).split("/")[i])
    except (TypeError, ValueError, IndexError, AttributeError):
        return None
