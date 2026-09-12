import { sql } from "@/lib/db";
import { num, signedPct } from "@/lib/format";

export const dynamic = "force-dynamic";
export const metadata = { title: "CFB — tracked picks" };

type Row = {
  id: number; fetched_at: string; season: number; week: number | null; game_date: string; kickoff_text: string | null;
  home_team: string; away_team: string; home_record: string | null; away_record: string | null;
  proj_home_score: string | null; proj_away_score: string | null; open_line: string | null; current_line: string | null; proj_line: string | null;
  pick_text: string; pick_line: string | null; pick_is_home: boolean | null; espn_id: string | null;
  home_score: number | null; away_score: number | null; result: string | null; profit_units: string | null; n_versions: number;
};

const day = (d: string) => new Date(d + "T12:00:00Z").toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric", timeZone: "UTC" });

export default async function CFB({ searchParams }: { searchParams: Promise<{ week?: string }> }) {
  const sp = await searchParams;
  const weeks = await sql<{ season: number; week: number }[]>`
    SELECT DISTINCT season, week FROM external_picks WHERE source = 'sasser_cfb' AND week IS NOT NULL ORDER BY season DESC, week DESC`;
  if (!weeks.length) return <Empty />;
  const cur = weeks.find((w) => String(w.week) === sp.week) ?? weeks[0];
  // one row per game: the LATEST pick version we saw (his board updates through the week); graded versions carry the result
  const rows = await sql<Row[]>`
    WITH v AS (
      SELECT p.*, g.home_score, g.away_score, g.result, g.profit_units,
             count(*) OVER (PARTITION BY p.season, p.game_date, p.home_team, p.away_team) AS n_versions,
             row_number() OVER (PARTITION BY p.season, p.game_date, p.home_team, p.away_team ORDER BY p.fetched_at DESC) AS rn
      FROM external_picks p LEFT JOIN external_grades g ON g.pick_id = p.id
      WHERE p.source = 'sasser_cfb' AND p.season = ${cur.season} AND p.week = ${cur.week})
    SELECT * FROM v WHERE rn = 1 ORDER BY game_date, kickoff_text, home_team`;
  const rec = await record(cur.season);

  const mins = (t: string | null) => { const m = t?.match(/(\d+):(\d+)\s*(AM|PM)/i); if (!m) return 1e9; return ((Number(m[1]) % 12) + (m[3].toUpperCase() === "PM" ? 12 : 0)) * 60 + Number(m[2]); };
  const byDay = new Map<string, Row[]>();
  for (const r of [...rows].sort((a, b) => a.game_date.localeCompare(b.game_date) || mins(a.kickoff_text) - mins(b.kickoff_text) || a.home_team.localeCompare(b.home_team))) {
    const d = day(r.game_date); byDay.set(d, [...(byDay.get(d) ?? []), r]);
  }
  const fetched = rows.length ? new Date(Math.max(...rows.map((r) => +new Date(r.fetched_at)))) : null;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="eyebrow">College football · tracked external picks</p>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight">David Sasser&apos;s board, week {cur.week}</h1>
          <p className="mt-1 max-w-2xl text-sm text-muted">
            Picks scraped from <a href="https://www.davidsasser.com/cfb" className="text-accent hover:underline" rel="noreferrer">davidsasser.com/cfb</a> — his
            margin model (CFBD Model Pick&apos;em builder <a href="https://predictions.collegefootballdata.com/user/%40davidsasser" className="text-accent hover:underline" rel="noreferrer">@davidsasser</a>: 1,851 games
            all-time, 52.9% ATS) played against the current line in every game. Not our model: we store every pick the moment we see it and grade it ourselves at −110 from the ESPN final, so
            the record below is independent of what his site claims.
          </p>
        </div>
        <form className="flex items-center gap-2 text-[13px]">
          <label className="text-muted">Week</label>
          <select name="week" defaultValue={String(cur.week)} className="select">
            {weeks.filter((w) => w.season === cur.season).map((w) => <option key={w.week} value={w.week}>Week {w.week}</option>)}
          </select>
          <button className="rounded bg-panel-2 px-2 py-1 hover:text-fg">Go</button>
        </form>
      </div>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <div className="card kpi"><div className="kpi-label">ATS (our grading)</div><div className="kpi-value">{rec.w}–{rec.l}–{rec.p}</div><div className="kpi-sub">{cur.season}, first version of each pick</div></div>
        <div className="card kpi"><div className="kpi-label">Win rate</div><div className="kpi-value">{rec.w + rec.l ? `${(100 * rec.w / (rec.w + rec.l)).toFixed(1)}%` : "–"}</div><div className="kpi-sub">break-even 52.4% at −110</div></div>
        <div className="card kpi"><div className="kpi-label">Units</div><div className={`kpi-value ${rec.units > 0 ? "text-up" : rec.units < 0 ? "text-down" : ""}`}>{rec.units >= 0 ? "+" : ""}{num(rec.units, 2)}u</div><div className="kpi-sub">1u flat at −110</div></div>
        <div className="card kpi"><div className="kpi-label">ROI</div><div className="kpi-value">{rec.w + rec.l + rec.p ? signedPct(rec.units / (rec.w + rec.l + rec.p)) : "–"}</div><div className="kpi-sub">{rec.w + rec.l + rec.p} graded · {rec.pending} pending</div></div>
      </div>

      {[...byDay.entries()].map(([d, list]) => (
        <section key={d} className="space-y-2">
          <h2 className="text-[12px] font-semibold uppercase tracking-wider text-muted">{d} · {list.length} games</h2>
          <div className="card overflow-x-auto p-0">
            <table className="data text-[13px]">
              <thead><tr><th>Kick (CT)</th><th>Team</th><th>Rec</th><th className="text-right">Proj</th><th>Open</th><th>Current</th><th>Proj. line</th><th>Pick</th><th>Result</th></tr></thead>
              <tbody>
                {list.map((r) => {
                  const final = r.home_score != null && r.away_score != null;
                  const cls = r.result === "win" ? "text-up" : r.result === "loss" ? "text-down" : "text-muted";
                  return [
                    <tr key={r.id + "a"} className="border-b-0">
                      <td rowSpan={2} className="whitespace-nowrap align-middle text-muted">{r.kickoff_text ?? "–"}</td>
                      <td className="font-medium">{r.away_team}{final && <span className="ml-2 font-mono text-muted">{r.away_score}</span>}</td>
                      <td className="text-muted">{r.away_record ?? ""}</td>
                      <td className="text-right font-mono">{r.proj_away_score == null ? "–" : num(r.proj_away_score, 1)}</td>
                      <td rowSpan={2} className="whitespace-nowrap align-middle">{r.open_line ?? "–"}</td>
                      <td rowSpan={2} className="whitespace-nowrap align-middle">{r.current_line ?? "–"}</td>
                      <td rowSpan={2} className="whitespace-nowrap align-middle">{r.proj_line ?? "–"}</td>
                      <td rowSpan={2} className="whitespace-nowrap align-middle"><span className="pill">{r.pick_text}</span>{Number(r.n_versions) > 1 && <span className="ml-1 text-[11px] text-muted" title="his pick changed during the week; every version is stored and the first one is what the record counts">×{r.n_versions}</span>}</td>
                      <td rowSpan={2} className={`align-middle ${cls}`}>{r.result ?? (final ? "grading…" : "")}{r.profit_units != null && <span className="ml-1 font-mono">{Number(r.profit_units) >= 0 ? "+" : ""}{num(r.profit_units, 2)}</span>}</td>
                    </tr>,
                    <tr key={r.id + "h"}>
                      <td className="font-medium">{r.home_team}{final && <span className="ml-2 font-mono text-muted">{r.home_score}</span>}</td>
                      <td className="text-muted">{r.home_record ?? ""}</td>
                      <td className="text-right font-mono">{r.proj_home_score == null ? "–" : num(r.proj_home_score, 1)}</td>
                    </tr>,
                  ];
                })}
              </tbody>
            </table>
          </div>
        </section>
      ))}
      <p className="text-[12px] text-muted">
        Board fetched {fetched ? fetched.toLocaleString("en-US", { timeZone: "America/New_York", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) + " ET" : "–"}; his site shows no prices, so every pick is graded at −110.
        Lines and projections are his, reproduced as shown. Nothing here is a recommendation.
      </p>
    </div>
  );
}

async function record(season: number) {
  const [r] = await sql<{ w: number; l: number; p: number; units: number; pending: number }[]>`
    WITH first_v AS (
      SELECT DISTINCT ON (season, game_date, home_team, away_team) id FROM external_picks
      WHERE source = 'sasser_cfb' AND season = ${season} ORDER BY season, game_date, home_team, away_team, fetched_at ASC)
    SELECT count(*) FILTER (WHERE g.result = 'win') AS w, count(*) FILTER (WHERE g.result = 'loss') AS l,
           count(*) FILTER (WHERE g.result = 'push') AS p, coalesce(sum(g.profit_units), 0) AS units,
           count(*) FILTER (WHERE g.id IS NULL) AS pending
    FROM first_v f LEFT JOIN external_grades g ON g.pick_id = f.id`;
  return { w: Number(r.w), l: Number(r.l), p: Number(r.p), units: Number(r.units), pending: Number(r.pending) };
}

function Empty() {
  return (
    <div className="space-y-2">
      <h1 className="text-2xl font-semibold tracking-tight">CFB</h1>
      <p className="text-sm text-muted">No picks tracked yet — the pipeline&apos;s <code>sasser_cfb</code> job hasn&apos;t run.</p>
    </div>
  );
}
