import { sql } from "@/lib/db";
import { american, ago, book, kickoff, num, pct, signedPct, TEAM_NAMES } from "@/lib/format";

export const dynamic = "force-dynamic";
export const metadata = { title: "L3 Defense vs. Line (experimental)" };

type Row = Record<string, any>;
const MK: Record<string, string> = { player_pass_yds: "Passing yds", player_rush_yds: "Rushing yds" };
const VER: Record<string, string> = { naive_v0: "naive_v0 (the original rule)", naive_g10: "naive_g10 (rule + 10% gap gate)", l3_v1: "l3_v1 (adjusted)" };
const VERSIONS = ["naive_v0", "naive_g10", "l3_v1"];

async function safe<T>(p: Promise<T>, fallback: T): Promise<T> {
  try { return await p; } catch { return fallback; }   // tables missing before the first run → empty page, not a crash
}

function Cond({ c }: { c?: string | null }) {
  if (c === "soft") return <span className="pill pill-up">soft</span>;
  if (c === "stingy") return <span className="pill pill-down">stingy</span>;
  return <span className="text-dim">–</span>;
}

function Verdict({ f }: { f?: Row }) {
  if (!f) return <span className="text-dim">not scored</span>;
  if (!f.side) return <span className="text-muted">no flag</span>;
  return (
    <span className={`font-semibold ${f.side === "Over" ? "text-up" : "text-down"}`}>
      {f.side} {num(f.line, 1)} <span className="font-normal text-muted">{american(Number(f.price_american))} {book(f.book)}</span>
    </span>
  );
}

function Ledger({ s }: { s: Row }) {
  const n = Number(s.n), w = Number(s.w), l = Number(s.l), units = Number(s.units ?? 0);
  return (
    <div className="card kpi">
      <div className="kpi-label">{VER[s.version] ?? s.version}</div>
      <div className="kpi-value">{w}-{l}{Number(s.p) ? `-${s.p}` : ""}</div>
      <div className="kpi-sub">
        {n ? <>{pct(w / Math.max(w + l, 1), 1)} · <span className={units >= 0 ? "text-up" : "text-down"}>{units >= 0 ? "+" : ""}{num(units, 2)}u</span> · ROI {signedPct(units / n)}</> : "no graded flags yet"}
        {s.clv != null && <> · CLV {signedPct(Number(s.clv))}</>}
      </div>
    </div>
  );
}

function BtLine({ k, s }: { k: string; s?: Row }) {
  if (!s || !s.n) return <tr><td>{k}</td><td colSpan={5} className="text-dim">no lines in backtest</td></tr>;
  return (
    <tr>
      <td className="font-medium">{k}</td>
      <td>{s.w}-{s.l}{s.p ? `-${s.p}` : ""}</td>
      <td>{pct(s.hit, 1)}</td>
      <td className={s.roi >= 0 ? "text-up" : "text-down"}>{signedPct(s.roi)}</td>
      <td>{s.ci_lo == null ? "–" : `[${signedPct(s.ci_lo)}, ${signedPct(s.ci_hi)}]`}</td>
      <td>{s.t == null ? "–" : Number(s.t).toFixed(2)}</td>
    </tr>
  );
}

export default async function L3Page() {
  const [latest] = await safe(sql`SELECT season, week, max(created_at) AS at FROM experimental_l3_defense GROUP BY 1,2 ORDER BY 1 DESC, 2 DESC LIMIT 1`, [] as Row[]);
  const season = latest?.season, week = latest?.week;
  const [defense, flags, ledger, meta, g10] = await Promise.all([
    latest ? safe(sql`SELECT DISTINCT ON (team) * FROM experimental_l3_defense WHERE season=${season} AND week=${week}
                      ORDER BY team, created_at DESC`, [] as Row[]) : Promise.resolve([] as Row[]),
    latest ? safe(sql`SELECT DISTINCT ON (version, player_id, market) f.*, s.taken_at AS line_at
                      FROM experimental_l3_flags f LEFT JOIN odds_snapshots s ON s.id = f.snapshot_id
                      LEFT JOIN experimental_l3_voids v ON v.flag_id = f.id
                      LEFT JOIN experimental_l3_void_revocations rv ON rv.flag_id = f.id
                      WHERE f.season=${season} AND f.week=${week} AND (v.id IS NULL OR rv.id IS NOT NULL)
                      ORDER BY version, player_id, market, f.created_at DESC`, [] as Row[]) : Promise.resolve([] as Row[]),
    // ledger: the FIRST flagged version of each pick (the price a follower could have taken), graded at that price
    safe(sql`WITH first AS (
               SELECT DISTINCT ON (version, season, week, player_id, market, side) f.id, f.version FROM experimental_l3_flags f
               LEFT JOIN experimental_l3_voids v ON v.flag_id = f.id
               LEFT JOIN experimental_l3_void_revocations rv ON rv.flag_id = f.id
               WHERE f.side IS NOT NULL AND (v.id IS NULL OR rv.id IS NOT NULL) ORDER BY f.version, f.season, f.week, f.player_id, f.market, f.side, f.created_at ASC)
             SELECT first.version, count(*) FILTER (WHERE g.result IN ('win','loss','push')) AS n,
                    count(*) FILTER (WHERE g.result='win') AS w, count(*) FILTER (WHERE g.result='loss') AS l,
                    count(*) FILTER (WHERE g.result='push') AS p, coalesce(sum(g.profit_units),0) AS units, avg(g.clv_prob) AS clv
             FROM first JOIN experimental_l3_grades g ON g.flag_id = first.id GROUP BY first.version`, [] as Row[]),
    safe(sql`SELECT * FROM experimental_l3_meta ORDER BY created_at DESC LIMIT 1`, [] as Row[]),
    // naive_g10 track record: every pick at its first flagged price, graded or pending
    safe(sql`WITH first AS (
               SELECT DISTINCT ON (f.season, f.week, f.player_id, f.market, f.side) f.* FROM experimental_l3_flags f
               LEFT JOIN experimental_l3_voids v ON v.flag_id = f.id
               LEFT JOIN experimental_l3_void_revocations rv ON rv.flag_id = f.id
               WHERE f.version = 'naive_g10' AND f.side IS NOT NULL AND (v.id IS NULL OR rv.id IS NOT NULL)
               ORDER BY f.season, f.week, f.player_id, f.market, f.side, f.created_at ASC)
             SELECT first.season, first.week, first.player_name, first.team, first.opponent, first.market, first.side,
                    first.line, first.price_american, first.price_decimal, first.book, first.player_l3, first.kickoff_utc,
                    g.actual, g.result, g.profit_units
             FROM first LEFT JOIN experimental_l3_grades g ON g.flag_id = first.id
             ORDER BY first.season DESC, first.week DESC, first.kickoff_utc ASC, first.player_name`, [] as Row[]),
  ]);
  const bt: Row = meta[0]?.backtest ?? {};
  const lean: Row = meta[0]?.lean_eligible ?? {};

  // one card per (player, market) holding both versions' verdicts
  const byKey = new Map<string, { naive?: Row; g10?: Row; v1?: Row }>();
  for (const f of flags) {
    const k = `${f.player_id}|${f.market}`;
    const e = byKey.get(k) ?? {};
    if (f.version === "naive_v0") e.naive = f; else if (f.version === "naive_g10") e.g10 = f; else e.v1 = f;
    byKey.set(k, e);
  }
  // (player L3 − line) / line, from the stored row so it works for every run
  const gapRaw = (f?: Row) => (f && f.player_l3 != null && Number(f.line) ? (Number(f.player_l3) - Number(f.line)) / Number(f.line) : null);
  const gapOf = (e: { naive?: Row }) => Math.abs(gapRaw(e.naive) ?? 0);
  const cards = [...byKey.values()].filter((e) => e.naive?.side || e.g10?.side || e.v1?.side)
    .sort((a, b) => Number(!!b.v1?.side) - Number(!!a.v1?.side) || Number(!!b.g10?.side) - Number(!!a.g10?.side) || gapOf(b) - gapOf(a));
  const nEvaluated = byKey.size;
  const ranAt = flags.reduce((m: Date | null, f) => (!m || new Date(f.created_at) > m ? new Date(f.created_at) : m), null);
  const lineAt = flags.find((f) => f.line_at)?.line_at;
  const trStatus = defense.length ? (defense.every((d) => d.tr_status === "ok") ? "matches" : defense.some((d) => d.tr_status === "unavailable") ? "unavailable" : `${defense.filter((d) => d.tr_status === "mismatch").length} teams differ`) : null;
  // naive_g10 tracker numbers (flat −110 alongside the actual price, so a lucky price doesn't flatter it)
  const FLAT = 100 / 110;
  const gr = g10.filter((r) => ["win", "loss", "push"].includes(r.result));
  const tW = gr.filter((r) => r.result === "win").length, tL = gr.filter((r) => r.result === "loss").length, tP = gr.filter((r) => r.result === "push").length;
  const tUnits = gr.reduce((a, r) => a + Number(r.profit_units ?? 0), 0);
  const tFlat = gr.reduce((a, r) => a + (r.result === "win" ? FLAT : r.result === "loss" ? -1 : 0), 0);
  const tPending = g10.filter((r) => !r.result).length;
  const weeks = [...new Set(g10.map((r) => `${r.season}|${r.week}`))].map((k) => {
    const rs = g10.filter((r) => `${r.season}|${r.week}` === k);
    const g = rs.filter((r) => ["win", "loss", "push"].includes(r.result));
    return { k, week: rs[0].week, season: rs[0].season, w: g.filter((r) => r.result === "win").length, l: g.filter((r) => r.result === "loss").length,
             p: g.filter((r) => r.result === "push").length, units: g.reduce((a, r) => a + Number(r.profit_units ?? 0), 0), pending: rs.filter((r) => !r.result).length };
  });
  const ledgerRows = VERSIONS.map((v) => ledger.find((r) => r.version === v) ?? { version: v, n: 0, w: 0, l: 0, p: 0, units: 0 });

  return (
    <div className="space-y-8">
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <p className="eyebrow">Experimental</p>
          <span className="pill pill-warn">Experimental — not a model pick</span>
        </div>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight">L3 Defense vs. Line{latest ? ` · ${season} Week ${week}` : ""}</h1>
        <p className="mt-2 max-w-3xl text-sm leading-relaxed text-muted">
          Haywood&apos;s rule: when a defense has been giving up a lot of passing or rushing yards over its last 3 games and the opposing QB&apos;s or RB&apos;s
          line is below his own last-3 average, lean Over (mirror for Under). <b className="text-fg-2">naive_v0</b> runs that rule exactly as stated; <b className="text-fg-2">naive_g10</b> also requires his last-3 average to differ from the line by at least 10% of the line.
          <b className="text-fg-2"> l3_v1</b> keeps the idea but rates defenses per play, adjusts for the offenses they faced, shrinks the 3-game sample, and prices a projection against the no-vig line.
          Both are graded on their own ledger below and never feed the screener or the stake sizing. Every flag is tagged <b>watch</b> until its backtest clears the publishing rule.
        </p>
        <p className="mt-2 text-[12px] text-dim">
          {ranAt ? <>Scored {ago(ranAt)}</> : "Not scored yet"}
          {lineAt && <> · lines fetched {ago(lineAt)}</>}
          {defense[0] && <> · defense data through {kickoff(defense[0].as_of)}</>}
          {trStatus && <> · TeamRankings cross-check: {trStatus}</>}
        </p>
      </div>

      <section id="g10-record">
        <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="h-section">Track record · rule + 10% gap gate</h2>
          <span className="text-[12px] text-muted">every naive_g10 pick, first flagged price, 1u each</span>
        </div>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
          {([
            ["Record", `${tW}-${tL}${tP ? `-${tP}` : ""}`, tPending ? `${tPending} pending` : "all graded"],
            ["Hit rate", tW + tL ? pct(tW / (tW + tL), 1) : "–", "wins ÷ decided"],
            ["Units", `${tUnits >= 0 ? "+" : ""}${num(tUnits, 2)}u`, "at the price shown"],
            ["At −110", `${tFlat >= 0 ? "+" : ""}${num(tFlat, 2)}u`, "every pick at −110"],
            ["ROI", gr.length ? signedPct(tUnits / gr.length) : "–", `${gr.length} graded`],
          ] as [string, string, string][]).map(([l, v, sub]) => (
            <div key={l} className="card kpi"><div className="kpi-label">{l}</div>
              <div className={`kpi-value ${l === "Units" || l === "At −110" ? (v.startsWith("+") ? "text-up" : v.startsWith("-") ? "text-down" : "") : ""}`}>{v}</div>
              <div className="kpi-sub">{sub}</div></div>
          ))}
        </div>
        {weeks.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-2 text-[12px]">
            {weeks.map((w) => (
              <span key={w.k} className="pill">
                Week {w.week}: {w.w}-{w.l}{w.p ? `-${w.p}` : ""}{w.pending ? ` (+${w.pending} pending)` : ""}
                <span className={w.units >= 0 ? "text-up" : "text-down"}>{w.units >= 0 ? "+" : ""}{num(w.units, 2)}u</span>
              </span>
            ))}
          </div>
        )}
        <div className="card mt-2 overflow-x-auto p-0">
          <table className="data text-[12.5px]">
            <thead><tr><th>Wk</th><th>Player</th><th>Bet</th><th>Price</th><th className="hidden sm:table-cell">His L3</th><th>Actual</th><th>Result</th><th>Units</th></tr></thead>
            <tbody>
              {g10.length === 0 && <tr><td colSpan={8} className="text-muted">No naive_g10 picks yet.</td></tr>}
              {g10.map((r, i) => (
                <tr key={i}>
                  <td>{r.week}</td>
                  <td><span className="font-medium">{r.player_name}</span> <span className="text-muted">{r.team} v {r.opponent}</span></td>
                  <td className={r.side === "Over" ? "text-up" : "text-down"}>{r.side} {num(r.line, 1)} <span className="text-muted">{r.market === "player_pass_yds" ? "pass" : "rush"}</span></td>
                  <td className="tnum">{american(Number(r.price_american))} <span className="text-muted">{book(r.book)}</span></td>
                  <td className="tnum hidden sm:table-cell">{num(r.player_l3, 1)}</td>
                  <td className="tnum">{r.actual == null ? "–" : num(r.actual, 0)}</td>
                  <td>{r.result === "win" ? <span className="pill pill-up">win</span> : r.result === "loss" ? <span className="pill pill-down">loss</span>
                      : r.result ? <span className="pill">{r.result}</span> : <span className="text-muted">pending</span>}</td>
                  <td className={`tnum ${Number(r.profit_units) > 0 ? "text-up" : Number(r.profit_units) < 0 ? "text-down" : ""}`}>{r.profit_units == null ? "–" : `${Number(r.profit_units) >= 0 ? "+" : ""}${num(r.profit_units, 2)}`}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-1 text-[11px] text-dim">Small samples swing hard: this rule's backtest is 96-84 (+1.8% at −110) and can't yet be told apart from luck.</p>
      </section>

      <section>
        <h2 className="h-section mb-2">Ledger (live, first flagged price)</h2>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">{ledgerRows.map((s) => <Ledger key={s.version} s={s} />)}</div>
      </section>

      <section>
        <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="h-section">Flags this week</h2>
          <span className="text-[12px] text-muted">{cards.length} flagged of {nEvaluated} QB/RB props evaluated</span>
        </div>
        {cards.length === 0 && <div className="card p-4 text-sm text-muted">No flags yet for this week. Runs Tuesday after the opening snapshot and Sunday 9am ET.</div>}
        <div className="grid gap-3 md:grid-cols-2">
          {cards.map((e) => {
            const f = (e.v1 ?? e.naive)!;
            const factors: Row[] = (e.v1?.side ? e.v1.factors : e.naive?.factors) ?? f.factors ?? [];
            const tag = [e.v1, e.g10, e.naive].some((x) => x?.tag === "lean") ? "lean" : "watch";
            return (
              <article key={`${f.player_id}|${f.market}`} className="card p-4">
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <p className="text-[11px] font-semibold uppercase tracking-wider text-muted">{f.position} · {MK[f.market]}</p>
                    <h3 className="text-base font-semibold">{f.player_name}</h3>
                    <p className="text-[12px] text-muted">{f.team} vs {f.opponent} · {kickoff(f.kickoff_utc)}</p>
                  </div>
                  <span className={`pill ${tag === "lean" ? "pill-accent" : ""}`}>{tag}</span>
                </div>
                <div className="mt-3 grid grid-cols-2 gap-2 text-[13px]">
                  <div><p className="kpi-label">naive_v0</p><Verdict f={e.naive} /></div>
                  <div><p className="kpi-label">naive_g10 (10% gate)</p><Verdict f={e.g10} /></div>
                  <div><p className="kpi-label">l3_v1</p><Verdict f={e.v1} /></div>
                  <div><p className="kpi-label">L3 vs line gap</p>{gapRaw(f) != null ? (
                    <span className={Math.abs(gapRaw(f)!) >= 0.1 ? "font-semibold text-up" : "text-muted"}>
                      {signedPct(gapRaw(f)!)} {Math.abs(gapRaw(f)!) >= 0.1 ? "· passes" : "· under 10%"}
                    </span>) : <span className="text-dim">–</span>}</div>
                  <div><p className="kpi-label">His L3 avg vs line</p><span className="tnum">{num(f.player_l3, 1)} vs {num(f.line, 1)}</span> <span className="text-dim">({f.player_l3_games})</span></div>
                  <div><p className="kpi-label">Projection · P(over)</p>{e.v1?.projection != null ? <span className="tnum">{num(e.v1.projection, 1)} · {pct(Number(e.v1.p_over), 0)} <span className="text-dim">mkt {pct(Number(f.fair_over), 0)}</span></span> : <span className="text-dim">–</span>}</div>
                  <div><p className="kpi-label">Defense (naive / v1)</p><Cond c={e.naive?.def_cond} /> <Cond c={e.v1?.def_cond} /></div>
                  <div><p className="kpi-label">Edge (v1)</p>{e.v1?.edge != null ? signedPct(Number(e.v1.edge)) : <span className="text-dim">–</span>}</div>
                </div>
                <ul className="mt-3 space-y-1 text-[13px] leading-snug">
                  {factors.map((x, i) => (
                    <li key={i} className="flex gap-2">
                      <span className={x.impact === "+" ? "text-up" : x.impact === "−" ? "text-down" : "text-muted"}>{x.impact === "+" ? "▲" : x.impact === "−" ? "▼" : "▬"}</span>
                      <span className="text-fg-2">{x.text}</span>
                    </li>
                  ))}
                </ul>
              </article>
            );
          })}
        </div>
      </section>

      <section>
        <h2 className="h-section mb-1">Defenses, last 3 games</h2>
        <p className="mb-2 text-[12px] text-muted">
          Yds/g = TeamRankings definition (pass net of sacks), rank 1 = fewest allowed; naive cut-offs 1–8 stingy, 25–32 soft. Per-play: raw L3 → opponent-adjusted
          (vs what those offenses usually gain) → shrunk toward the prior (B = weight on the 3-game sample). v1 condition = shrunk beyond ±1 SD of the league and the 80% interval excludes average.
        </p>
        <div className="card overflow-x-auto p-0">
          <table className="data text-[12.5px]">
            <thead>
              <tr>
                <th>Team</th><th>Pass yds/g L3</th><th>TR</th><th>naive</th><th>Yds/db raw</th><th>adj</th><th>shrunk (B)</th><th>z</th><th>v1</th>
                <th>Rush yds/g L3</th><th>TR</th><th>naive</th><th>Yds/carry raw</th><th>adj</th><th>shrunk (B)</th><th>z</th><th>v1</th>
              </tr>
            </thead>
            <tbody>
              {[...defense].sort((a, b) => Number(a.pass_naive_rank) - Number(b.pass_naive_rank)).map((d) => {
                const p = d.stats?.pass_ypd ?? {}, r = d.stats?.rush_ypc ?? {};
                return (
                  <tr key={d.team}>
                    <td><span className="font-medium">{d.team}</span> <span className="hidden text-muted lg:inline">{TEAM_NAMES[d.team]}</span></td>
                    <td className="tnum">{num(d.pass_ypg_l3, 1)} <span className="text-xs text-muted">#{d.pass_naive_rank}</span></td>
                    <td className="tnum text-muted">{num(d.tr_pass_l3, 1)}</td>
                    <td><Cond c={d.pass_naive_cond} /></td>
                    <td className="tnum">{num(p.raw, 2)}</td>
                    <td className="tnum">{p.adj == null ? "–" : `${p.adj >= 0 ? "+" : ""}${num(p.adj, 2)}`}</td>
                    <td className="tnum">{p.shrunk == null ? "–" : `${p.shrunk >= 0 ? "+" : ""}${num(p.shrunk, 2)}`} <span className="text-xs text-muted">({num(p.shrink, 2)})</span></td>
                    <td className="tnum">{num(p.z, 1)}</td>
                    <td><Cond c={d.pass_v1_cond} /></td>
                    <td className="tnum">{num(d.rush_ypg_l3, 1)} <span className="text-xs text-muted">#{d.rush_naive_rank}</span></td>
                    <td className="tnum text-muted">{num(d.tr_rush_l3, 1)}</td>
                    <td><Cond c={d.rush_naive_cond} /></td>
                    <td className="tnum">{num(r.raw, 2)}</td>
                    <td className="tnum">{r.adj == null ? "–" : `${r.adj >= 0 ? "+" : ""}${num(r.adj, 2)}`}</td>
                    <td className="tnum">{r.shrunk == null ? "–" : `${r.shrunk >= 0 ? "+" : ""}${num(r.shrunk, 2)}`} <span className="text-xs text-muted">({num(r.shrink, 2)})</span></td>
                    <td className="tnum">{num(r.z, 1)}</td>
                    <td><Cond c={d.rush_v1_cond} /></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      <section>
        <h2 className="h-section mb-1">Backtest (closing lines, DK/FD/Pinnacle)</h2>
        <p className="mb-2 text-[12px] text-muted">
          Weeks 4–18 only (the last-3 inputs need three games). Passing yards 2023–2025, rushing yards 2025 only (older rushing lines not bought yet). A flag becomes a <b>lean</b> only with ≥150 graded backtest bets and a 95% CI lower bound on ROI above −2%.
          Status: {Object.keys(lean).length ? Object.entries(lean).map(([k, v]) => `${k.replace("|", " · ")}: ${v ? "lean" : "watch"}`).join(" · ") : "not fitted yet"}. Full tables in docs/L3_BACKTEST.md.
        </p>
        <div className="card overflow-x-auto p-0">
          <table className="data text-[13px]">
            <thead><tr><th>At a flat −110 · version · market</th><th>W-L-P</th><th>Hit</th><th>ROI</th><th>95% CI</th><th>t</th></tr></thead>
            <tbody>
              {VERSIONS.flatMap((v) => [
                <BtLine key={v + "all"} k={`${v} · all`} s={bt[`flat110|${v}|all`]} />,
                ...["player_pass_yds", "player_rush_yds"].map((m) => <BtLine key={v + m} k={`${v} · ${MK[m]}`} s={bt[`flat110|${v}|${m}`]} />),
              ])}
            </tbody>
            <thead><tr><th>At the best actual closing price</th><th>W-L-P</th><th>Hit</th><th>ROI</th><th>95% CI</th><th>t</th></tr></thead>
            <tbody>
              {VERSIONS.flatMap((v) => ["player_pass_yds", "player_rush_yds"].map((m) => <BtLine key={v + m + "c"} k={`${v} · ${MK[m]}`} s={bt[`${v}|${m}`]} />))}
            </tbody>
          </table>
        </div>
        {["player_pass_yds", "player_rush_yds"].map((m) => bt[`base_rate_over|${m}`] && (
          <p key={m} className="mt-1 text-[12px] text-dim">Base rate, {MK[m]}: {pct(bt[`base_rate_over|${m}`].over_rate, 1)} of {bt[`base_rate_over|${m}`].n} priced lines went Over.</p>
        ))}
      </section>
    </div>
  );
}
