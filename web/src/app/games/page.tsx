import Link from "next/link";
import { sql } from "@/lib/db";
import { TEAM_NAMES, american, book, num } from "@/lib/format";

export const dynamic = "force-dynamic";
export const metadata = { title: "Games — spread projections" };

type Row = {
  id: number; created_at: string; season: number; week: number; game_id: string; home_team: string; away_team: string; kickoff_utc: string;
  home_record: string; away_record: string; proj_margin_raw: string; proj_margin: string; proj_total: string;
  proj_home_score: string; proj_away_score: string; open_spread: string | null; current_spread: string | null; sharp_spread: string | null;
  current_total: string | null; gap_raw: string | null; gap: string | null; pick_side: string | null; pick_line: string | null;
  pick_book: string | null; pick_price_american: number | null; pick_p_cover: string | null; pick_edge: string | null; lean_plus: boolean;
  home_score: number | null; away_score: number | null; result: string | null;
};

const fmtLine = (team: string, spread: number | null) => (spread == null ? "–" : `${team} ${spread > 0 ? "+" : ""}${spread % 1 === 0 ? spread.toFixed(0) : spread.toFixed(1)}`);
/** Show a home handicap as "favourite −x" the way books print it. */
const fav = (home: string, away: string, homeSpread: number | null) => {
  if (homeSpread == null) return "–";
  if (homeSpread === 0) return "PK";
  return homeSpread < 0 ? fmtLine(home, homeSpread) : fmtLine(away, -homeSpread);
};
const kick = (s: string) => new Date(s).toLocaleString("en-US", { timeZone: "America/New_York", weekday: "short", hour: "numeric", minute: "2-digit" });
const day = (s: string) => new Date(s).toLocaleDateString("en-US", { timeZone: "America/New_York", weekday: "long", month: "long", day: "numeric" });

export default async function Games({ searchParams }: { searchParams: Promise<{ week?: string }> }) {
  const sp = await searchParams;
  const weeks = await sql<{ season: number; week: number }[]>`SELECT DISTINCT season, week FROM spread_projections ORDER BY season DESC, week DESC`;
  if (!weeks.length) return <Empty />;
  const cur = weeks.find((w) => String(w.week) === sp.week) ?? (await currentWeek(weeks));
  // latest projection per game for the week, plus the actual score and the graded result of the FIRST pick version
  const rows = await sql<Row[]>`
    WITH p AS (
      SELECT DISTINCT ON (game_id) * FROM spread_projections WHERE season = ${cur.season} AND week = ${cur.week}
      ORDER BY game_id, created_at DESC),
    first_pick AS (
      SELECT DISTINCT ON (c.game_id) c.game_id, g.result FROM cards c LEFT JOIN grades g ON g.card_id = c.id
      WHERE c.market = 'spreads' AND c.source = 'model' AND c.season = ${cur.season} AND c.week = ${cur.week}
      ORDER BY c.game_id, c.created_at ASC)
    SELECT p.*, rg.home_score, rg.away_score, fp.result
    FROM p JOIN raw_games rg USING (game_id) LEFT JOIN first_pick fp USING (game_id)
    ORDER BY p.kickoff_utc, p.game_id`;
  const rec = await record(cur.season);

  const byDay = new Map<string, Row[]>();
  for (const r of rows) { const d = day(r.kickoff_utc); byDay.set(d, [...(byDay.get(d) ?? []), r]); }
  const updated = rows.length ? new Date(Math.max(...rows.map((r) => +new Date(r.created_at)))) : null;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="eyebrow">NFL · spreads &amp; totals</p>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight">Week {cur.week} projections</h1>
          <p className="mt-1 max-w-2xl text-sm text-muted">
            A ratings model (Elo + EPA, rest, QB changes) projects every game&apos;s score with no market input, then is compared with the line —
            the same recipe as the CFB boards this layout copies. The pick is the side the model favours against the current line in every game,
            shown as a lean, not a stake: out of sample a ratings model does not beat NFL closing spreads (47.9% ATS 2019–2025,
            <Link href="/how" className="text-accent hover:underline"> MODEL.md</Link>), and the record below is graded live to keep proving or disproving that.
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
        <div className="card kpi"><div className="kpi-label">Straight up</div><div className="kpi-value">{rec.su_w}–{rec.su_l}{rec.su_t ? `–${rec.su_t}` : ""}</div><div className="kpi-sub">projected winner, {cur.season}</div></div>
        <div className="card kpi"><div className="kpi-label">Against the spread</div><div className="kpi-value">{rec.ats_w}–{rec.ats_l}–{rec.ats_p}</div><div className="kpi-sub">every pick at the price shown</div></div>
        <div className="card kpi"><div className="kpi-label">ATS units</div><div className={`kpi-value ${rec.units > 0 ? "text-up" : rec.units < 0 ? "text-down" : ""}`}>{rec.units >= 0 ? "+" : ""}{num(rec.units, 2)}u</div><div className="kpi-sub">1u flat, {rec.ats_w + rec.ats_l + rec.ats_p} picks</div></div>
        <div className="card kpi"><div className="kpi-label">MAE vs market</div><div className="kpi-value">{rec.mae_model == null ? "–" : num(rec.mae_model, 2)} <span className="text-[13px] text-muted">/ {rec.mae_market == null ? "–" : num(rec.mae_market, 2)}</span></div><div className="kpi-sub">projected margin vs closing line</div></div>
      </div>

      {[...byDay.entries()].map(([d, list]) => (
        <section key={d} className="space-y-2">
          <h2 className="text-[12px] font-semibold uppercase tracking-wider text-muted">{d}</h2>
          <div className="card overflow-x-auto p-0">
            <table className="data text-[13px]">
              <thead>
                <tr><th>Kick (ET)</th><th>Team</th><th>Rec</th><th className="text-right">Proj</th><th>Open</th><th>Current</th><th>Proj. line</th><th>Pick</th><th>P(cover)</th><th>Result</th></tr>
              </thead>
              <tbody>
                {list.map((r) => {
                  const cs = r.current_spread == null ? null : Number(r.current_spread);
                  const os = r.open_spread == null ? null : Number(r.open_spread);
                  const pm = Number(r.proj_margin_raw);
                  const projLine = fav(r.home_team, r.away_team, -Math.round(pm * 2) / 2);
                  const pickTxt = r.pick_side ? `${r.pick_side} ${Number(r.pick_line) > 0 ? "+" : ""}${Number(r.pick_line)}` : "–";
                  const final = r.home_score != null && r.away_score != null;
                  const rowCls = r.result === "win" ? "text-up" : r.result === "loss" ? "text-down" : "text-muted";
                  return [
                    <tr key={r.id + "a"} className="border-b-0">
                      <td rowSpan={2} className="whitespace-nowrap align-middle text-muted"><Link href={`/games/${r.game_id}`} className="hover:text-fg">{kick(r.kickoff_utc)}</Link></td>
                      <td className="font-medium">{r.away_team} <span className="text-muted">{TEAM_NAMES[r.away_team]?.split(" ").slice(-1)[0]}</span>{final && <span className="ml-2 font-mono text-muted">{r.away_score}</span>}</td>
                      <td className="text-muted">{r.away_record}</td>
                      <td className="text-right font-mono">{num(r.proj_away_score, 1)}</td>
                      <td rowSpan={2} className="whitespace-nowrap align-middle">{fav(r.home_team, r.away_team, os)}</td>
                      <td rowSpan={2} className="whitespace-nowrap align-middle">{fav(r.home_team, r.away_team, cs)}{r.current_total != null && <span className="ml-1 text-muted">o/u {Number(r.current_total)}</span>}</td>
                      <td rowSpan={2} className="whitespace-nowrap align-middle" title={`blended toward the market: ${fav(r.home_team, r.away_team, -Math.round(Number(r.proj_margin) * 2) / 2)}`}>{projLine}{r.gap_raw != null && <span className="ml-1 text-[11px] text-muted">({Number(r.gap_raw) > 0 ? "+" : ""}{Number(r.gap_raw).toFixed(1)})</span>}</td>
                      <td rowSpan={2} className="whitespace-nowrap align-middle">
                        {r.pick_side ? (<>
                          <span className={`pill ${r.lean_plus ? "pill-up" : ""}`}>{pickTxt}</span>
                          <span className="ml-1 text-muted">{r.pick_price_american != null ? american(r.pick_price_american) : ""} {r.pick_book ? book(r.pick_book) : ""}</span>
                          {r.lean_plus && <span className="ml-1 text-[11px] text-muted" title="raw model disagrees with the market by 5+ points (the only bucket that was profitable 2019–2025, thinly)">lean+</span>}
                        </>) : "–"}
                      </td>
                      <td rowSpan={2} className="align-middle font-mono">{r.pick_p_cover == null ? "–" : `${(Number(r.pick_p_cover) * 100).toFixed(0)}%`}</td>
                      <td rowSpan={2} className={`align-middle ${rowCls}`}>{r.result ?? (final ? "grading…" : "")}</td>
                    </tr>,
                    <tr key={r.id + "h"}>
                      <td className="font-medium">{r.home_team} <span className="text-muted">{TEAM_NAMES[r.home_team]?.split(" ").slice(-1)[0]}</span>{final && <span className="ml-2 font-mono text-muted">{r.home_score}</span>}</td>
                      <td className="text-muted">{r.home_record}</td>
                      <td className="text-right font-mono">{num(r.proj_home_score, 1)}</td>
                    </tr>,
                  ];
                })}
              </tbody>
            </table>
          </div>
        </section>
      ))}
      <p className="text-[12px] text-muted">
        Lines are the median home handicap across DraftKings, FanDuel and Pinnacle at the week&apos;s first (open) and latest snapshot; the pick&apos;s price is the best of those books at that line.
        Projected line is the raw model (the number in brackets is its gap to the market, in points); hover to see the projection blended toward the market, which is what MODEL.md says you should actually believe.
        {updated && <> Last scored {updated.toLocaleString("en-US", { timeZone: "America/New_York", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })} ET.</>}
        {" "}Layout after <a href="https://www.davidsasser.com/cfb" className="hover:text-fg" rel="noreferrer">davidsasser.com/cfb</a>; his CFB picks are tracked on the <Link href="/cfb" className="text-accent hover:underline">CFB tab</Link>.
      </p>
    </div>
  );
}

async function currentWeek(weeks: { season: number; week: number }[]) {
  // the latest week that still has a game ahead of us, else the most recent week scored
  const r = await sql<{ season: number; week: number }[]>`
    SELECT season, week FROM spread_projections WHERE kickoff_utc > now() - interval '4 hours' ORDER BY season, week LIMIT 1`;
  return r[0] ?? weeks[0];
}

async function record(season: number) {
  const [r] = await sql<{ su_w: number; su_l: number; su_t: number; ats_w: number; ats_l: number; ats_p: number; units: number; mae_model: number | null; mae_market: number | null }[]>`
    WITH p AS (
      SELECT DISTINCT ON (game_id) game_id, proj_margin FROM spread_projections WHERE season = ${season} ORDER BY game_id, created_at ASC),
    su AS (
      SELECT count(*) FILTER (WHERE sign(p.proj_margin) = sign(g.home_score - g.away_score) AND g.home_score <> g.away_score) AS w,
             count(*) FILTER (WHERE sign(p.proj_margin) <> sign(g.home_score - g.away_score) AND g.home_score <> g.away_score) AS l,
             count(*) FILTER (WHERE g.home_score = g.away_score) AS t,
             avg(abs(p.proj_margin - (g.home_score - g.away_score))) AS mae_model,
             avg(abs(g.spread_line - (g.home_score - g.away_score))) FILTER (WHERE g.spread_line IS NOT NULL) AS mae_market
      FROM p JOIN raw_games g USING (game_id) WHERE g.home_score IS NOT NULL),
    fp AS (
      SELECT DISTINCT ON (c.game_id) c.game_id, gr.result, gr.profit_units FROM cards c JOIN grades gr ON gr.card_id = c.id
      WHERE c.market = 'spreads' AND c.source = 'model' AND c.season = ${season} ORDER BY c.game_id, c.created_at ASC),
    ats AS (
      SELECT count(*) FILTER (WHERE result = 'win') AS w, count(*) FILTER (WHERE result = 'loss') AS l,
             count(*) FILTER (WHERE result = 'push') AS p, coalesce(sum(profit_units), 0) AS units FROM fp)
    SELECT su.w AS su_w, su.l AS su_l, su.t AS su_t, ats.w AS ats_w, ats.l AS ats_l, ats.p AS ats_p, ats.units, su.mae_model, su.mae_market FROM su, ats`;
  return { ...r, units: Number(r.units), su_w: Number(r.su_w), su_l: Number(r.su_l), su_t: Number(r.su_t), ats_w: Number(r.ats_w), ats_l: Number(r.ats_l), ats_p: Number(r.ats_p),
    mae_model: r.mae_model == null ? null : Number(r.mae_model), mae_market: r.mae_market == null ? null : Number(r.mae_market) };
}

function Empty() {
  return (
    <div className="space-y-2">
      <h1 className="text-2xl font-semibold tracking-tight">Games</h1>
      <p className="text-sm text-muted">No spread projections yet — the pipeline&apos;s <code>score_spreads</code> job hasn&apos;t run for this week.</p>
    </div>
  );
}
