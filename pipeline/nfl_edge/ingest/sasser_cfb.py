"""David Sasser's college football board (https://www.davidsasser.com/cfb) → external_picks, graded via ESPN.

He submits a margin model to the CFBD Model Pick'em contest (predictions.collegefootballdata.com/user/@davidsasser:
1,851 games all-time, 52.9% ATS, MAE 12.55 — market level) and publishes every game on his site with a pick against
the current line. We store each pick as shown (append-only: a new row whenever the pick text changes), grade it at
−110 against the ESPN final, and show the record on /cfb. Nothing here is our model; it is a tracked external source.

Page structure (server-rendered Next.js, Sept 2026):
  <section aria-labelledby="day-friday-september-11"> <h3>Friday, September 11</h3> ... <article aria-labelledby="{espnId}-title">
    <header><div><span>6:30 PM CT</span><span>ESPN2</span></div><p>venue</p></header>
    <h3 id="{espnId}-title">Away at Home</h3>
    team blocks: <strong>Team</strong><span>0–1</span> ... <span>Projected score </span><strong>26.5</strong>
    <dl> Open / Current / Proj. Line </dl>  <div><span>Model picks</span><div><strong>Boston College −3.0</strong></div></div>
The ESPN event id in the article's aria-labelledby is what lets us grade without a CFB data subscription.
"""
from __future__ import annotations
import datetime as dt
import re
import requests
import pandas as pd
from bs4 import BeautifulSoup
from .. import db
from ..sources.espn import _HDR

URL = "https://www.davidsasser.com/cfb"
SOURCE = "sasser_cfb"
ESPN_CFB = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/summary"
MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"], 1)}


def _num(s: str) -> float | None:
    s = s.replace("−", "-").replace("–", "-").replace("+", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def parse_board(html: str, fetched: dt.datetime | None = None) -> list[dict]:
    """Every game on the page → dict with the fields of external_picks (pick_text may be '' when he shows none)."""
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)
    season = int(m.group(1)) if (m := re.search(r"(20\d\d)\s+COLLEGE FOOTBALL", text, re.I)) else (fetched or dt.datetime.now()).year
    week = int(m.group(1)) if (m := re.search(r"Week\s+(\d+)", text)) else None
    out = []
    for sec in soup.select('section[aria-labelledby^="day-"]'):
        h = sec.find(["h2", "h3"])
        date = None
        if h and (m := re.search(r"([A-Za-z]+),\s+([A-Za-z]+)\s+(\d+)", h.get_text(strip=True))):
            mon, dd = MONTHS.get(m.group(2).lower()), int(m.group(3))
            if mon:
                date = dt.date(season, mon, dd)
        for art in sec.select('article[aria-labelledby$="-title"]'):
            espn_id = art["aria-labelledby"].replace("-title", "")
            title = art.find("h3").get_text(" ", strip=True)
            mt = re.match(r"(.+?)\s+(?:at|vs\.?)\s+(.+)", title)
            if not mt:
                continue
            away, home = mt.group(1).strip(), mt.group(2).strip()
            strongs = [s.get_text(strip=True) for s in art.select("strong")]
            # team blocks: [Away, proj_away, Home, proj_home, ...pick]
            recs = [s.get_text(strip=True) for s in art.select("span > span + span") if re.fullmatch(r"\d+[–-]\d+(?:[–-]\d+)?", s.get_text(strip=True))]
            proj = [s.get_text(strip=True) for s in art.select("span > strong") if re.fullmatch(r"\d+(\.\d+)?", s.get_text(strip=True))]
            dl = {d.dt.get_text(strip=True): d.dd.get_text(" ", strip=True) for d in art.select("dl > div") if d.dt and d.dd}
            pick_el = None
            for s in art.select("span"):
                if s.get_text(strip=True).lower() == "model picks":
                    pick_el = s.find_next("strong")
                    break
            pick_text = pick_el.get_text(" ", strip=True) if pick_el else ""
            pick_team, pick_line, is_home = None, None, None
            if pick_text and (pm := re.match(r"(.+?)\s+([−+-]?\d+(?:\.\d+)?)$", pick_text)):
                pick_team, pick_line = pm.group(1).strip(), _num(pm.group(2))
                is_home = pick_team == home if pick_team in (home, away) else None
            kick = art.select_one("header span")
            out.append({
                "source": SOURCE, "fetched_at": fetched, "season": season, "week": week, "sport": "cfb", "game_date": date,
                "kickoff_text": kick.get_text(strip=True) if kick else None, "home_team": home, "away_team": away,
                "home_record": recs[1] if len(recs) > 1 else None, "away_record": recs[0] if recs else None,
                "proj_away_score": _num(proj[0]) if proj else None, "proj_home_score": _num(proj[1]) if len(proj) > 1 else None,
                "open_line": dl.get("Open"), "current_line": dl.get("Current"), "proj_line": dl.get("Proj. Line"),
                "pick_team": pick_team, "pick_line": pick_line, "pick_text": pick_text, "pick_is_home": is_home, "espn_id": espn_id,
            })
    return out


def ingest_sasser_cfb(html: str | None = None) -> int:
    now = dt.datetime.now(dt.timezone.utc)
    if html is None:
        r = requests.get(URL, headers={**_HDR, "Accept": "text/html"}, timeout=30)
        r.raise_for_status()
        html = r.text
    rows = [x for x in parse_board(html, now) if x["pick_text"]]
    if not rows:
        print("[sasser] no picks parsed"); return 0
    with db.JobRun("ingest_sasser_cfb") as run:
        df = pd.DataFrame(rows)
        # append-only: the unique key includes pick_text, so a changed pick becomes a new row and the old one stays
        n = db.upsert(df, "external_picks", ["source", "season", "game_date", "home_team", "away_team", "pick_text"], update=False)
        run.rows = n
        print(f"[sasser] {len(rows)} games on the board, {n} rows written (season {rows[0]['season']} week {rows[0]['week']})")
        return n


def fetch_cfb_final(espn_id: str) -> dict | None:
    """→ {'state', 'home', 'away', 'home_score', 'away_score'} from the ESPN college football summary."""
    try:
        j = requests.get(ESPN_CFB, params={"event": espn_id}, headers=_HDR, timeout=20).json()
    except Exception as e:
        print(f"[sasser] espn {espn_id}: {e}"); return None
    comp = ((j.get("header") or {}).get("competitions") or [{}])[0]
    st = ((comp.get("status") or {}).get("type") or {}).get("state")
    t = {}
    for x in comp.get("competitors", []) or []:
        t[x.get("homeAway")] = {"name": (x.get("team") or {}).get("displayName"), "score": int(x["score"]) if str(x.get("score", "")).lstrip("-").isdigit() else None}
    return {"state": st, "home": t.get("home", {}).get("name"), "away": t.get("away", {}).get("name"),
            "home_score": t.get("home", {}).get("score"), "away_score": t.get("away", {}).get("score")}


def grade_pick(pick_line: float, is_home: bool, home_score: int, away_score: int, dec: float = 1 + 100 / 110) -> tuple[str, float]:
    margin = (home_score - away_score) if is_home else (away_score - home_score)
    adj = margin + pick_line
    if adj == 0:
        return "push", 0.0
    return ("win", dec - 1) if adj > 0 else ("loss", -1.0)


def grade_sasser_cfb() -> int:
    """Grade every ungraded pick whose game date has passed, at −110 (his site shows no price)."""
    picks = db.read_sql("""SELECT p.* FROM external_picks p LEFT JOIN external_grades g ON g.pick_id = p.id
                           WHERE g.id IS NULL AND p.source = :s AND p.game_date <= :d AND p.pick_line IS NOT NULL AND p.pick_is_home IS NOT NULL
                           ORDER BY p.game_date""", {"s": SOURCE, "d": dt.date.today()})
    if picks.empty:
        print("[sasser] nothing to grade"); return 0
    rows, finals = [], {}
    with db.JobRun("grade_sasser_cfb") as run:
        for p in picks.itertuples():
            f = finals.get(p.espn_id) or fetch_cfb_final(p.espn_id)
            finals[p.espn_id] = f
            if not f or f["state"] != "post" or f["home_score"] is None:
                continue
            result, profit = grade_pick(float(p.pick_line), bool(p.pick_is_home), f["home_score"], f["away_score"])
            rows.append({"pick_id": int(p.id), "home_score": f["home_score"], "away_score": f["away_score"], "result": result,
                         "profit_units": profit, "espn_id": p.espn_id})
        run.rows = db.append(pd.DataFrame(rows), "external_grades") if rows else 0
        print(f"[sasser] graded {run.rows} of {len(picks)} pending picks")
        return run.rows
