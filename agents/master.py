"""Master agent for NFL Edge Finder (Claude Agent SDK).

One orchestrator ("master") that plans and delegates to three narrow specialists:
  ops      - checks the pipeline ran (GitHub Actions + DB), re-runs the L3 jobs if they didn't
  analyst  - builds this week's @level4props card from the L3 flags + injury news
  critic   - re-checks every card line against the database; read-only, never edits

Run from /pipeline:   python ../agents/master.py "thursday" | "sunday" | "<any plain-English task>"

Output: the master's final report is appended to the agent_reports table (shown on the members-only /agent
page) and, if DISCORD_WEBHOOK_URL is set, posted to Discord. Picks are NEVER printed to stdout: the repo is
public, so GitHub Actions logs are public. The log only shows status, turns and cost.

Guard rails: permission_mode="dontAsk" + an allow-list (anything not listed is refused, no prompt);
SQL goes through agents/sql.py (READ ONLY transaction); a $ budget, a turn cap, a wall-clock timeout,
subagents cannot spawn subagents. The agents cannot post anywhere, edit code, or place bets.
"""
from __future__ import annotations
import asyncio
import json
import os
import sys
import urllib.request

from claude_agent_sdk import AgentDefinition, ClaudeAgentOptions, ResultMessage, query

MODEL = os.environ.get("AGENT_MODEL", "claude-opus-5-5")
BUDGET_USD = float(os.environ.get("AGENT_BUDGET_USD", "3.0"))
TIMEOUT_S = int(os.environ.get("AGENT_TIMEOUT_S", "1800"))
SITE = "https://nfl-edge-finder.vercel.app"
SQL = 'python ../agents/sql.py "<SELECT ...>"'

# The current week's naive_g10 plays at the newest snapshot, excluding voids (minus revocations) and games
# that have kicked off. gap_pct = (player's last-3 avg - line) / line.
CARD_SQL = """SELECT f.id, f.player_name, f.position, f.team, f.opponent, f.market, f.side, f.line, f.price_american, f.book,
 f.kickoff_utc, f.player_l3, f.player_l3_games, f.def_cond, f.injury_status, f.season, f.week, f.run_label, f.created_at,
 round(100*(f.player_l3-f.line)/f.line,1) AS gap_pct
FROM experimental_l3_flags f
WHERE f.version='naive_g10' AND f.side IS NOT NULL
  AND f.snapshot_id=(SELECT snapshot_id FROM experimental_l3_flags WHERE version='naive_g10' ORDER BY created_at DESC LIMIT 1)
  AND f.kickoff_utc > now()
  AND NOT EXISTS (SELECT 1 FROM experimental_l3_voids v WHERE v.flag_id=f.id
                  AND NOT EXISTS (SELECT 1 FROM experimental_l3_void_revocations r WHERE r.flag_id=f.id))
ORDER BY abs((f.player_l3-f.line)/f.line) DESC""".replace("\n", " ")

RECORD_SQL = """SELECT count(*) FILTER (WHERE g.result='win') w, count(*) FILTER (WHERE g.result='loss') l,
 count(*) FILTER (WHERE g.result='push') p, round(sum(g.profit_units),2) units
FROM experimental_l3_grades g JOIN experimental_l3_flags f ON f.id=g.flag_id
WHERE f.version='naive_g10' AND g.result IN ('win','loss','push')""".replace("\n", " ")

MASTER = f"""You are the master agent for NFL Edge Finder, working for Haywood. You plan and delegate; specialists do
the deep work. Specialists: ops (pipeline health, re-runs L3 jobs), analyst (builds the @level4props card),
critic (verifies the card against the database). Give every specialist a COMPLETE brief: it sees nothing
of this conversation, only your Agent-tool prompt.

Standard tasks:
- "thursday": ops first (did today's `snapshot --label thu` and an L3 scoring run succeed? if not, fix by running
  the L3 jobs), then analyst, then critic. On critic FAIL send the exact fix list back to analyst; stop after 2
  rounds and report outstanding objections.
- "sunday": same flow; ops checks the 13:00 UTC gameday_am run. Analyst also re-checks injuries (inactives).
- anything else: Haywood's plain-English request. Do what it asks within your tools, or say clearly what you
  could not do and what he needs to do.

Hard rules:
- You and your specialists can only: read the database through `{SQL}` (read-only), run the whitelisted
  pipeline jobs, read GitHub Actions run status with `gh run list` / `gh run view`, read files, and search/fetch
  the web. You cannot post to X, log bets on Action Network, change code, or place bets — Haywood's Chrome-based
  Sunday run does posting and Action tracking from your report.
- Never invent a line, price, player or record. Every number in the report comes from a query or a cited page.
- Odds API credits are scarce: never run `snapshot` unless the scheduled one failed AND api_usage shows
  credits_remaining > 1500 on the latest row.
- You are running unattended. A message without a tool call ends the run. Do not stop with a plan, an offer to
  continue, or a milestone summary; keep going until the report is complete. Time matters: finish early.

Your FINAL message is the report, in markdown, exactly these sections:
## Pipeline health  (each scheduled job this week: ok / failed + one-line cause; what you re-ran)
## This week's plays  (table: player, team vs opp, market, side, line, price, book, kickoff ET, L3 avg, gap %, flags)
## Free Play  (one play: largest |gap %| with no role-change risk and player not out; one-line why)
## X posts  (ready to paste, minimal style:  "Free Play\\n\\n<Player> <Over|Under> <line> <Pass Yds|Rush Yds> (1u)"
   and "Week N Card\\n\\n" + one line per other play; plus the pinned line "Record since Week 4: W-L (+u)")
## Action Network list  (one line per play: player, Over/Under, line, market — for Haywood's tracking run)
## Critic  (PASS, or the outstanding objections)
## Needs Haywood  (anything only he can do; "nothing" if none)
"""

OPS = AgentDefinition(
    description="Pipeline health: checks GitHub Actions runs and the database for this week's snapshot/scoring "
                "runs and re-runs the L3 jobs when needed. Use first on every thursday/sunday task.",
    prompt=f"""You check that the NFL Edge Finder pipeline did its job this week and fix only what you are allowed to.
Tools: `gh run list --workflow pipeline.yml --limit 30 --json databaseId,event,status,conclusion,createdAt,displayTitle`
and `gh run view <id> --log-failed` (read the failing step); database via `{SQL}`.
Allowed re-runs (run from the current directory): `python -m nfl_edge score_l3_experiment --label <thu|sun_am>`,
`python -m nfl_edge grade_l3_experiment`, and — ONLY if the scheduled snapshot failed and the latest api_usage
row shows credits_remaining > 1500 — `python -m nfl_edge snapshot --label <thu|sun_am>`.
Freshness check: SELECT max(created_at), run_label FROM experimental_l3_flags GROUP BY run_label ORDER BY 1 DESC LIMIT 5;
and SELECT ts, credits_remaining FROM api_usage ORDER BY ts DESC LIMIT 3.
Never edit files. Return: each run this week (ok/failed + cause), what you re-ran and its outcome, flag
freshness (newest run_label + time), credits remaining. Plain list, no prose.""",
    tools=["Bash", "Read", "Grep"],
    effort="low",
)

ANALYST = AgentDefinition(
    description="Builds this week's @level4props card from the L3 naive_g10 flags plus injury news. Use after ops.",
    prompt=f"""You build the weekly @level4props card. Source of truth is the database (read-only): `{SQL}`.
1. Current plays:  {CARD_SQL}
2. Record since Week 4 (site ledger):  {RECORD_SQL}
3. For each play check injury/role news for the player AND key teammates (starter out → backup promoted,
   committee changes) with WebSearch/WebFetch (ESPN injuries, team news). Mark: OUT (drop it), questionable,
   role risk (one line why), or clear.
4. Free Play = the play with the largest |gap_pct| that is clear (no role risk, not questionable).
Return: the table of plays with columns player, team vs opp, market, side, line, price, book, kickoff (ET),
player_l3 (and games), gap_pct, def_cond, injury/role note; the Free Play with a one-line reason; the record
(W-L-P, units); source URLs for every injury claim. Never invent numbers; if a query fails, say so.""",
    tools=["Bash", "WebSearch", "WebFetch", "Read"],
    effort="medium",
)

CRITIC = AgentDefinition(
    description="Verifies a finished card against the database. Use after every analyst draft, before the report is final.",
    prompt=f"""You verify a betting card someone else built. You never edit it. Database (read-only): `{SQL}`.
For every play in the card you are given, query experimental_l3_flags by player_name for the current week and
check: side, line, price and book match the newest naive_g10 row; |gap %| >= 10 (the naive_g10 gate);
kickoff_utc is in the future; the play is not voided. Check the Free Play is the largest-gap play without an
injury/role flag. Check the record numbers against experimental_l3_grades.
Return PASS, or FAIL followed by a numbered list of specific fixes.""",
    tools=["Bash", "Read"],
    effort="medium",
)

ALLOWED = [
    "Agent", "Read", "Grep", "Glob", "WebSearch", "WebFetch",
    "Bash(python ../agents/sql.py:*)",
    "Bash(python -m nfl_edge score_l3_experiment:*)",
    "Bash(python -m nfl_edge grade_l3_experiment:*)",
    "Bash(python -m nfl_edge snapshot:*)",
    "Bash(gh run list:*)",
    "Bash(gh run view:*)",
]


def _discord(text: str) -> None:
    url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not url:
        return
    chunks = [text[i:i + 1900] for i in range(0, len(text), 1900)][:4]
    chunks[-1] += f"\n\nFull report: {SITE}/agent"
    for c in chunks:
        req = urllib.request.Request(url, data=json.dumps({"content": c}).encode(),
                                     headers={"Content-Type": "application/json", "User-Agent": "nfl-edge-master"})
        try:
            urllib.request.urlopen(req, timeout=15).read()
        except Exception as e:  # delivery is best-effort; the report is already in the DB
            print(f"[master] discord post failed: {e.__class__.__name__}")


def _store(task: str, status: str, cost: float | None, turns: int | None, report: str) -> None:
    from nfl_edge.db import execute
    execute("""CREATE TABLE IF NOT EXISTS agent_reports (id bigserial PRIMARY KEY, created_at timestamptz NOT NULL DEFAULT now(),
               task text NOT NULL, status text NOT NULL, cost_usd numeric, turns int, report text NOT NULL)""")
    execute("INSERT INTO agent_reports (task, status, cost_usd, turns, report) VALUES (:t, :s, :c, :n, :r)",
            {"t": task, "s": status, "c": cost, "n": turns, "r": report})


async def run(task: str) -> tuple[str, float | None, int | None, str]:
    opts = ClaudeAgentOptions(
        model=MODEL,
        system_prompt=MASTER,
        agents={"ops": OPS, "analyst": ANALYST, "critic": CRITIC},
        allowed_tools=ALLOWED,
        disallowed_tools=["Write", "Edit", "NotebookEdit"],
        permission_mode="dontAsk",
        setting_sources=[],
        max_turns=60,
        max_budget_usd=BUDGET_USD,
        effort="medium",
        cwd=os.getcwd(),
        env={"CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH": "1", "CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS": "4"},
    )
    prompt = f"Task: {task}\n(For the current date/time, query SELECT now() through sql.py.)"
    async for m in query(prompt=prompt, options=opts):
        if isinstance(m, ResultMessage):
            return m.subtype, m.total_cost_usd, m.num_turns, (m.result or "")
    return "no_result", None, None, ""


def main() -> int:
    task = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("TASK", "thursday")).strip() or "thursday"
    try:
        status, cost, turns, report = asyncio.run(asyncio.wait_for(run(task), timeout=TIMEOUT_S))
    except asyncio.TimeoutError:
        status, cost, turns, report = "timeout", None, None, f"Master agent hit the {TIMEOUT_S}s hard stop before finishing."
    except Exception as e:
        status, cost, turns, report = "error", None, None, f"Master agent crashed: {e.__class__.__name__}: {e}"
    if not report.strip():
        report = f"(no report; run ended with status {status})"
    header = f"**Master agent — task `{task}` — {status}**" + (f" · ${cost:.2f}" if cost is not None else "") + "\n\n"
    try:
        _store(task, status, cost, turns, report)
    except Exception as e:
        print(f"[master] could not store report: {e.__class__.__name__}")
    _discord(header + report)
    # Public log: status only, never picks.
    print(f"[master] task={task!r} status={status} turns={turns} cost={cost}")
    return 0 if status == "success" else 1


if __name__ == "__main__":
    sys.exit(main())
