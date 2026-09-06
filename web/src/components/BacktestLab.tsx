"use client";
import { useEffect, useMemo, useState } from "react";
import { MARKET_NAMES, pct, signedPct } from "@/lib/format";
import { barFor } from "@/lib/thresholds";
import { kellyFull, DEFAULT_BANKROLL, DEFAULT_FRACTION, MAX_STAKE_PCT, WEEKLY_EXPOSURE_PCT, exposureScale } from "@/lib/kelly";

const FRACTIONS = [[1, "Full Kelly"], [0.5, "Half Kelly"], [0.25, "Quarter Kelly (default)"], [0.125, "Eighth Kelly"]] as const;

type Bet = { season: number; week: number; market: string; player: string; team: string; opp: string; book: string; line: number; side: string;
  dec: number; fair: number; p: number; p_cal: number | null; edge: number; actual: number | null; result: "win" | "loss" | "push" };

type Payload = { cols: string[]; rows: unknown[][]; generated_at: string };

function parse(pl: Payload): Bet[] {
  return pl.rows.map((r) => Object.fromEntries(pl.cols.map((c, i) => [c, r[i]])) as unknown as Bet);
}

/** Re-runs the closing-line backtest under the screener's own rules: which edge counts as a bet, and how Kelly sizes it.
 *  Bankroll is held fixed (no compounding) so the units are comparable with the live track record. */
export function BacktestLab() {
  const [data, setData] = useState<Bet[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [season, setSeason] = useState<string>("");
  const [market, setMarket] = useState("");
  const [edgeReq, setEdgeReq] = useState<string>("");
  const [useCal, setUseCal] = useState(true);
  const [bankroll, setBankroll] = useState(DEFAULT_BANKROLL);
  const [fraction, setFraction] = useState<number>(DEFAULT_FRACTION);
  const [cap, setCap] = useState(MAX_STAKE_PCT * 100);
  const [exposure, setExposure] = useState(WEEKLY_EXPOSURE_PCT * 100);
  const [showWeeks, setShowWeeks] = useState(false);

  useEffect(() => {
    fetch("/api/backtest.json").then((r) => r.json()).then((pl: Payload) => setData(parse(pl))).catch((e) => setErr(String(e)));
  }, []);

  const seasons = useMemo(() => (data ? [...new Set(data.map((b) => b.season))].sort() : []), [data]);
  const markets = useMemo(() => (data ? [...new Set(data.map((b) => b.market))] : []), [data]);

  const sim = useMemo(() => {
    if (!data) return null;
    const bar = (m: string) => (edgeReq === "" ? barFor(m) : Number(edgeReq) / 100);
    const pFor = (b: Bet) => (useCal && b.p_cal != null ? b.p_cal : b.p);
    const stakeRaw = (b: Bet) => {
      const f = kellyFull(pFor(b), b.dec);
      if (f <= 0) return 0;
      const st = Math.round(Math.min(f * fraction, cap / 100) * bankroll * 20) / 20;
      return st >= 0.1 ? st : 0;
    };
    const picked = data.filter((b) => b.edge >= bar(b.market) && (!season || b.season === Number(season)) && (!market || b.market === market));
    // week-level exposure scaling, exactly as the screener does it
    const byWeek = new Map<string, Bet[]>();
    for (const b of picked) { const k = `${b.season}-${b.week}`; (byWeek.get(k) ?? byWeek.set(k, []).get(k)!).push(b); }
    const wkNum = (k: string) => { const [s, w] = k.split("-").map(Number); return s * 100 + w; };
    const weeks = [...byWeek.entries()].sort(([a], [b]) => wkNum(a) - wkNum(b)).map(([key, bets]) => {
      const raw = bets.map(stakeRaw);
      const scale = exposureScale(raw, bankroll, exposure / 100);
      let staked = 0, pnl = 0, exp = 0, flat = 0, w = 0, l = 0, p = 0;
      bets.forEach((b, i) => {
        const st = Math.round(raw[i] * scale * 20) / 20;
        if (st <= 0) return;
        staked += st;
        const pr = pFor(b);
        exp += st * (pr * (b.dec - 1) - (1 - pr));
        if (b.result === "win") { pnl += st * (b.dec - 1); flat += b.dec - 1; w++; }
        else if (b.result === "loss") { pnl -= st; flat -= 1; l++; }
        else p++;
      });
      const [s, wk] = key.split("-").map(Number);
      return { season: s, week: wk, n: w + l + p, w, l, p, staked, pnl, exp, flat, scale };
    });
    const tot = weeks.reduce((a, x) => ({ n: a.n + x.n, w: a.w + x.w, l: a.l + x.l, p: a.p + x.p, staked: a.staked + x.staked, pnl: a.pnl + x.pnl, exp: a.exp + x.exp, flat: a.flat + x.flat }),
      { n: 0, w: 0, l: 0, p: 0, staked: 0, pnl: 0, exp: 0, flat: 0 });
    // equity curve + drawdown
    let eq = 0, peak = 0, maxDD = 0;
    const curve = weeks.map((x) => { eq += x.pnl; peak = Math.max(peak, eq); maxDD = Math.max(maxDD, peak - eq); return { key: `${x.season} W${x.week}`, eq }; });
    const mean = weeks.length ? tot.pnl / weeks.length : 0;
    const sd = weeks.length > 1 ? Math.sqrt(weeks.reduce((a, x) => a + (x.pnl - mean) ** 2, 0) / (weeks.length - 1)) : 0;
    // per market / per season breakdowns at the same stakes
    const group = (key: (b: Bet) => string) => {
      const m = new Map<string, { n: number; w: number; l: number; staked: number; pnl: number; flat: number }>();
      for (const [k, bets] of byWeek) {
        const raw = bets.map(stakeRaw), scale = exposureScale(raw, bankroll, exposure / 100);
        bets.forEach((b, i) => {
          const st = Math.round(raw[i] * scale * 20) / 20; if (st <= 0) return;
          const g = m.get(key(b)) ?? { n: 0, w: 0, l: 0, staked: 0, pnl: 0, flat: 0 };
          g.n++; g.staked += st;
          if (b.result === "win") { g.w++; g.pnl += st * (b.dec - 1); g.flat += b.dec - 1; }
          else if (b.result === "loss") { g.l++; g.pnl -= st; g.flat -= 1; }
          m.set(key(b), g);
        });
        void k;
      }
      return [...m.entries()].sort();
    };
    return { weeks, tot, curve, maxDD, mean, sd, byMarket: group((b) => b.market), bySeason: group((b) => String(b.season)), nPicked: picked.length };
  }, [data, season, market, edgeReq, useCal, bankroll, fraction, cap, exposure]);

  const sel = "select";
  if (err) return <p className="text-sm text-down">Could not load backtest data: {err}</p>;
  if (!data || !sim) return <p className="text-sm text-muted">Loading {data ? "" : "16k closing-line bets"}…</p>;
  const { tot } = sim;
  const roi = tot.staked ? tot.pnl / tot.staked : 0;
  const winRate = tot.w + tot.l ? tot.w / (tot.w + tot.l) : 0;

  return (
    <div className="space-y-4">
      <div className="card flex min-w-0 flex-wrap items-end gap-x-4 gap-y-3 overflow-hidden p-4 text-[13px]">
        <div>
          <p className="eyebrow mb-1.5">Which bets</p>
          <div className="flex flex-wrap items-end gap-2">
            <label className="flex flex-col gap-1 text-[12px] text-muted">Season
              <select className={sel} value={season} onChange={(e) => setSeason(e.target.value)}>
                <option value="">All seasons</option>
                {seasons.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-[12px] text-muted">Market
              <select className={sel} value={market} onChange={(e) => setMarket(e.target.value)}>
                <option value="">All markets</option>
                {markets.map((m) => <option key={m} value={m}>{MARKET_NAMES[m] ?? m}</option>)}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-[12px] text-muted">Edge requirement
              <select className={sel} value={edgeReq} onChange={(e) => setEdgeReq(e.target.value)}>
                <option value="">Market bars — passing 6%, others 8%</option>
                {[2, 3, 4, 5, 6, 8, 10, 12, 15, 20].map((v) => <option key={v} value={v}>≥ {v}% every market</option>)}
              </select>
            </label>
          </div>
        </div>
        <div>
          <p className="eyebrow mb-1.5">Stake sizing (Kelly)</p>
          <div className="flex flex-wrap items-end gap-2">
            <label className="flex flex-col gap-1 text-[12px] text-muted">Bankroll (units)
              <input type="number" className={`${sel} w-24`} value={bankroll} min={1} onChange={(e) => setBankroll(+e.target.value || 1)} />
            </label>
            <label className="flex flex-col gap-1 text-[12px] text-muted">Kelly fraction
              <select className={sel} value={fraction} onChange={(e) => setFraction(+e.target.value)}>
                {FRACTIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-[12px] text-muted">Cap per bet (% of bankroll)
              <input type="number" className={`${sel} w-20`} value={cap} min={0.1} max={100} step={0.5} onChange={(e) => setCap(+e.target.value || 0.1)} />
            </label>
            <label className="flex flex-col gap-1 text-[12px] text-muted">Weekly exposure (% of bankroll)
              <input type="number" className={`${sel} w-20`} value={exposure} min={1} max={1000} step={5} onChange={(e) => setExposure(+e.target.value || 1)} />
            </label>
            <label className="flex items-center gap-1.5 pb-2 text-[12px] text-muted">
              <input type="checkbox" checked={useCal} onChange={(e) => setUseCal(e.target.checked)} /> size off calibrated probability
            </label>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
        <Kpi label="Bets" value={String(tot.n)} sub={`${tot.w}-${tot.l}${tot.p ? `-${tot.p}` : ""} · ${pct(winRate, 1)}`} />
        <Kpi label="Staked" value={`${tot.staked.toFixed(0)}u`} sub={`${sim.weeks.length} weeks · ${sim.weeks.length ? (tot.staked / sim.weeks.length).toFixed(1) : 0}u/week`} />
        <Kpi label="Profit" value={`${tot.pnl >= 0 ? "+" : ""}${tot.pnl.toFixed(1)}u`} tone={tot.pnl >= 0 ? "up" : "down"} sub={`${signedPct(roi)} on stakes · ${signedPct(bankroll ? tot.pnl / bankroll : 0)} of bankroll`} />
        <Kpi label="Expected" value={`${tot.exp >= 0 ? "+" : ""}${tot.exp.toFixed(1)}u`} sub={useCal ? "calibrated model" : "raw model"} />
        <Kpi label="Flat 1u" value={`${tot.flat >= 0 ? "+" : ""}${tot.flat.toFixed(1)}u`} sub={`${signedPct(tot.n ? tot.flat / tot.n : 0)} ROI`} tone={tot.flat >= 0 ? "up" : "down"} />
        <Kpi label="Max drawdown" value={`−${sim.maxDD.toFixed(1)}u`} sub={`weekly ${sim.mean >= 0 ? "+" : ""}${sim.mean.toFixed(1)}u ± ${sim.sd.toFixed(1)}u`} tone="down" />
      </div>

      <section className="card p-4 sm:p-5">
        <h2 className="eyebrow mb-2">Cumulative profit by week (units)</h2>
        <Curve pts={sim.curve} />
      </section>

      <div className="grid gap-4 md:grid-cols-2">
        <Breakdown title="By market" rows={sim.byMarket.map(([k, g]) => [MARKET_NAMES[k] ?? k, g])} />
        <Breakdown title="By season" rows={sim.bySeason.map(([k, g]) => [k, g])} />
      </div>

      <section className="card p-4 sm:p-5">
        <button className="eyebrow" onClick={() => setShowWeeks((v) => !v)}>{showWeeks ? "▾" : "▸"} By week ({sim.weeks.length})</button>
        {showWeeks && (
          <div className="mt-2 overflow-x-auto">
            <table className="w-full text-[13px] tnum">
              <thead className="text-left text-xs text-muted"><tr><th>Week</th><th>Bets</th><th>Record</th><th>Staked</th><th>Scale</th><th>Expected</th><th>Profit</th><th>Flat 1u</th></tr></thead>
              <tbody>
                {sim.weeks.map((w) => (
                  <tr key={`${w.season}-${w.week}`} className="border-t border-border/60">
                    <td className="py-1">{w.season} W{w.week}</td><td>{w.n}</td><td>{w.w}-{w.l}{w.p ? `-${w.p}` : ""}</td><td>{w.staked.toFixed(1)}u</td>
                    <td className="text-muted">{w.scale < 1 ? `×${w.scale.toFixed(2)}` : "–"}</td>
                    <td>{w.exp >= 0 ? "+" : ""}{w.exp.toFixed(2)}u</td>
                    <td className={w.pnl >= 0 ? "text-up" : "text-down"}>{w.pnl >= 0 ? "+" : ""}{w.pnl.toFixed(2)}u</td>
                    <td className={w.flat >= 0 ? "text-up" : "text-down"}>{w.flat >= 0 ? "+" : ""}{w.flat.toFixed(1)}u</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <p className="text-[12px] leading-relaxed text-muted">
        Every bet is placed at the real closing line and best available US price (The Odds API history), graded against the actual stat, and voided
        when the player recorded no attempt. Bankroll is held at {bankroll}u throughout (no compounding) so units are comparable with the live track
        record. Confidence is not applied here — it is computed live from data that isn&apos;t stored for historical weeks. Passing yards cover 2023–25;
        receiving yards, receptions and rushing yards cover 2025 only, so those results are one season of evidence, not three.
      </p>
    </div>
  );
}

function Kpi({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: "up" | "down" }) {
  return (
    <div className="card kpi min-w-0">
      <div className="kpi-label">{label}</div>
      <div className={`kpi-value ${tone === "up" ? "text-up" : tone === "down" ? "text-down" : ""}`}>{value}</div>
      {sub && <div className="kpi-sub">{sub}</div>}
    </div>
  );
}

function Breakdown({ title, rows }: { title: string; rows: [string, { n: number; w: number; l: number; staked: number; pnl: number; flat: number }][] }) {
  return (
    <section className="card p-4 sm:p-5">
      <h2 className="eyebrow mb-2">{title}</h2>
      <table className="w-full text-[13px] tnum">
        <thead className="text-left text-xs text-muted"><tr><th></th><th>Bets</th><th>Win %</th><th>Staked</th><th>Profit</th><th>ROI</th><th>Flat 1u</th></tr></thead>
        <tbody>
          {rows.map(([k, g]) => (
            <tr key={k} className="border-t border-border/60">
              <td className="py-1">{k}</td><td>{g.n}</td><td>{g.w + g.l ? pct(g.w / (g.w + g.l), 1) : "–"}</td><td>{g.staked.toFixed(0)}u</td>
              <td className={g.pnl >= 0 ? "text-up" : "text-down"}>{g.pnl >= 0 ? "+" : ""}{g.pnl.toFixed(1)}u</td>
              <td>{g.staked ? signedPct(g.pnl / g.staked) : "–"}</td>
              <td className={g.flat >= 0 ? "text-up" : "text-down"}>{g.flat >= 0 ? "+" : ""}{g.flat.toFixed(1)}u</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function Curve({ pts }: { pts: { key: string; eq: number }[] }) {
  if (!pts.length) return <p className="text-sm text-muted">No bets under these settings.</p>;
  const W = 720, H = 210, padL = 40, padR = 8, padT = 22, padB = 24;
  const ys = pts.map((p) => p.eq);
  const lo = Math.min(0, ...ys), hi = Math.max(0, ...ys);
  const span = hi - lo || 1;
  const x = (i: number) => padL + (i / Math.max(pts.length - 1, 1)) * (W - padL - padR);
  const y = (v: number) => padT + (1 - (v - lo) / span) * (H - padT - padB);
  const path = pts.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.eq).toFixed(1)}`).join(" ");
  const area = `M${x(0).toFixed(1)},${y(0)} ` + pts.map((p, i) => `L${x(i).toFixed(1)},${y(p.eq).toFixed(1)}`).join(" ") + ` L${x(pts.length - 1).toFixed(1)},${y(0)} Z`;
  const last = pts[pts.length - 1];
  const step = Math.max(1, Math.ceil(pts.length / 8));
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="Cumulative profit">
      <path d={area} fill={last.eq >= 0 ? "var(--up)" : "var(--down)"} opacity="0.12" />
      <line x1={padL} x2={W - padR} y1={y(0)} y2={y(0)} stroke="var(--border)" />
      <path d={path} fill="none" stroke="var(--accent)" strokeWidth="2" />
      {[lo, 0, hi].filter((v, i, a) => a.indexOf(v) === i).map((v) => (
        <text key={v} x={padL - 6} y={y(v) + 4} fill="var(--muted)" fontSize="10" textAnchor="end">{v.toFixed(0)}u</text>
      ))}
      {pts.map((p, i) => ((i % step === 0 && pts.length - 1 - i >= step / 2) || i === pts.length - 1) && (
        <text key={p.key} x={x(i)} y={H - 6} fill="var(--muted)" fontSize="10" textAnchor={i === pts.length - 1 ? "end" : "middle"}>{p.key}</text>
      ))}
      <circle cx={x(pts.length - 1)} cy={y(last.eq)} r="3" fill={last.eq >= 0 ? "var(--up)" : "var(--down)"} />
      <text x={x(pts.length - 1) - 6} y={y(last.eq) - 8} fill="var(--fg)" fontSize="11" textAnchor="end">{last.eq >= 0 ? "+" : ""}{last.eq.toFixed(1)}u</text>
    </svg>
  );
}
