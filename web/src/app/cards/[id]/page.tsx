import Link from "next/link";
import { notFound } from "next/navigation";
import { cardById, projection, lineHistory, playerGameLog, opponentLastGames, teamInjuries } from "@/lib/queries";
import { american, book, kickoff, MARKET_NAMES, num, pct, signedPct, TEAM_NAMES } from "@/lib/format";
import { FactorList } from "@/components/FactorList";
import { DistChart } from "@/components/DistChart";

export const dynamic = "force-dynamic";

export default async function CardPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const c = await cardById(Number(id));
  if (!c) notFound();
  const [proj, hist, log, oppLog, inj] = await Promise.all([
    projection(c.projection_id), lineHistory(c.event_id ?? "", c.market, c.player_name),
    playerGameLog(c.player_id), opponentLastGames(c.opponent), teamInjuries(c.season, c.week, [c.team, c.opponent]),
  ]);
  const usedMean = Number(c.factors.find((f) => f.factor === "projection")?.value ?? proj?.mean ?? 0);
  const sideCls = c.side === "Over" ? "text-up" : "text-down";
  const matchup = c.team === c.home_team ? `${c.opponent} @ ${c.team}` : `${c.team} @ ${c.opponent}`;
  const line = Number(c.line);
  const bySnap = new Map<string, { taken_at: string; label: string; lines: number[] }>();
  for (const h of hist) {
    const k = String(h.snapshot_id);
    if (!bySnap.has(k)) bySnap.set(k, { taken_at: h.taken_at, label: h.label, lines: [] });
    if (h.side === "Over") bySnap.get(k)!.lines.push(Number(h.line));
  }
  const hits = log.filter((g) => Number(g.passing_yards) > line).length;

  return (
    <div className="space-y-6">
      <div>
        <Link href="/" className="text-xs text-muted hover:underline">← This week</Link>
        <div className="mt-1 flex flex-wrap items-baseline gap-x-2">
          <span className="rounded bg-panel-2 px-1.5 py-0.5 text-xs text-muted">{c.position}</span>
          <h1 className="text-2xl font-semibold tracking-tight">
            {c.player_name} · {MARKET_NAMES[c.market] ?? c.market} <span className={sideCls}>{c.side.toUpperCase()} {line}</span>
          </h1>
          <span className="text-sm text-muted tnum">{american(c.price_american)} {book(c.book)} (best)</span>
        </div>
        <p className="text-sm text-muted">{matchup} · {kickoff(c.kickoff_utc)} · {c.published ? "Published pick" : "Below publish threshold"} · scored {new Date(c.created_at).toLocaleString("en-US", { timeZone: "America/New_York" })} ET</p>
      </div>

      <div className="grid grid-cols-3 gap-2 text-center text-sm tnum sm:grid-cols-5">
        {[["Edge", signedPct(Number(c.edge))], ["Model", pct(Number(c.model_prob), 1)], ["Market (no-vig)", pct(Number(c.market_prob), 1)],
          ["Confidence", String(c.confidence)], ["EV / $1", `${num(Number(c.ev_per_unit) * 100, 1)}¢`]].map(([l, v]) => (
          <div key={l} className="card px-2 py-2.5"><div className="kpi-label">{l}</div><div className="font-semibold">{v}</div></div>
        ))}
      </div>

      <section className="card p-4 sm:p-5">
        <h2 className="eyebrow mb-2">Projection</h2>
        {proj && <DistChart mean={usedMean} sd={Number(proj.sd)} line={line} side={c.side} />}
        {proj && (
          <p className="mt-1 text-xs text-muted tnum">
            Raw model {num(proj.mean)} · market-anchored {num(usedMean)} · sd {num(proj.sd)} · P10 {num(proj.q10, 0)} · P25 {num(proj.q25, 0)} · P50 {num(proj.q50, 0)} · P75 {num(proj.q75, 0)} · P90 {num(proj.q90, 0)}
          </p>
        )}
      </section>

      <section className="card p-4 sm:p-5">
        <h2 className="eyebrow mb-2">Why</h2>
        <FactorList factors={c.factors} season={c.season} week={c.week} />
      </section>

      <div className="grid gap-4 md:grid-cols-2">
        <section className="card p-4 sm:p-5">
          <h2 className="eyebrow mb-2">Book by book</h2>
          <table className="w-full text-sm tnum">
            <thead className="text-left text-xs text-muted"><tr><th>Book</th><th>Line</th><th>Over</th><th>Under</th></tr></thead>
            <tbody>
              {c.book_prices.map((b) => (
                <tr key={b.book + b.line} className={b.book === c.book && Number(b.line) === line ? "text-accent" : ""}>
                  <td className="py-0.5">{book(b.book)}</td><td>{b.line}</td><td>{american(b.over)}</td><td>{american(b.under)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
        <section className="card p-4 sm:p-5">
          <h2 className="eyebrow mb-2">Line movement</h2>
          {bySnap.size === 0 ? <p className="text-sm text-muted">No snapshots yet.</p> : (
            <table className="w-full text-sm tnum">
              <thead className="text-left text-xs text-muted"><tr><th>Snapshot</th><th>Taken (ET)</th><th>Consensus line</th><th>Range</th></tr></thead>
              <tbody>
                {[...bySnap.values()].map((s, i) => {
                  const sorted = [...s.lines].sort((a, b) => a - b);
                  const med = sorted.length ? sorted[Math.floor(sorted.length / 2)] : null;
                  return (
                    <tr key={i}><td className="py-0.5">{s.label}</td><td>{new Date(s.taken_at).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZone: "America/New_York" })}</td>
                      <td>{med ?? "–"}</td><td>{sorted.length ? `${sorted[0]}–${sorted[sorted.length - 1]}` : "–"}</td></tr>
                  );
                })}
              </tbody>
            </table>
          )}
          {c.line_open != null && <p className="mt-1 text-xs text-muted">Opened at {Number(c.line_open)} (consensus).</p>}
        </section>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <section className="card p-4 sm:p-5">
          <h2 className="eyebrow mb-2">{c.player_name} — last {log.length} starts vs {line}</h2>
          <p className="mb-2 text-xs text-muted">Over in {hits} of {log.length}. Source: nflverse weekly stats.</p>
          <table className="w-full text-sm tnum">
            <thead className="text-left text-xs text-muted"><tr><th>Wk</th><th>Opp</th><th>Att</th><th>Yds</th><th>TD</th></tr></thead>
            <tbody>
              {log.map((g) => (
                <tr key={`${g.season}-${g.week}`} className={Number(g.passing_yards) > line ? "text-up" : "text-down"}>
                  <td className="py-0.5">{g.season} W{g.week}</td><td>{g.opponent}</td><td>{g.attempts}</td><td>{g.passing_yards}</td><td>{g.passing_tds}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
        <section className="card p-4 sm:p-5">
          <h2 className="eyebrow mb-2">{TEAM_NAMES[c.opponent]} — last {oppLog.length} QBs faced</h2>
          <p className="mb-2 text-xs text-muted">Passing yards allowed to the opposing starter. <Link href={`/rankings/defense?season=${c.season}&week=${c.week}&team=${c.opponent}`} className="text-accent">Full ranking ↗</Link></p>
          <table className="w-full text-sm tnum">
            <thead className="text-left text-xs text-muted"><tr><th>Wk</th><th>QB</th><th>Yds</th></tr></thead>
            <tbody>
              {oppLog.map((g, i) => (
                <tr key={i}><td className="py-0.5">{g.season} W{g.week}</td><td>{g.player_name} ({g.offense})</td><td className={Number(g.passing_yards) > line ? "text-up" : ""}>{g.passing_yards}</td></tr>
              ))}
            </tbody>
          </table>
        </section>
      </div>

      <section className="card p-4 sm:p-5">
        <h2 className="eyebrow mb-2">Injury report · {c.team} & {c.opponent}</h2>
        {inj.length === 0 ? <p className="text-sm text-muted">Official report not yet published for this week (confidence is reduced until it is).</p> : (
          <ul className="grid gap-1 text-sm sm:grid-cols-2">
            {inj.map((r, i) => <li key={i}><span className="text-muted">{r.team}</span> {r.full_name} ({r.position}) — {r.report_status ?? r.practice_status}{r.report_primary_injury ? `, ${r.report_primary_injury}` : ""}</li>)}
          </ul>
        )}
      </section>
    </div>
  );
}
