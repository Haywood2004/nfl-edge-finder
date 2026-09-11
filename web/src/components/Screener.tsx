"use client";
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import type { Card } from "@/lib/queries";
import { american, book, kickoff, MARKET_NAMES, pct, signedPct } from "@/lib/format";
import { barFor, MIN_CONF, BARS_TEXT } from "@/lib/thresholds";
import { kellyFull, DEFAULT_BANKROLL, DEFAULT_FRACTION, MAX_STAKE_PCT, WEEKLY_EXPOSURE_PCT, exposureScale } from "@/lib/kelly";

const FRACTIONS = [[1, "Full Kelly"], [0.5, "Half Kelly"], [0.25, "Quarter Kelly (default)"], [0.125, "Eighth Kelly"]] as const;

type SortKey = "score" | "edge" | "confidence" | "stake" | "kickoff";

/** One table for everything the model priced this week. Default view = the bets (each market's bar + confidence ≥ 55). */
export function Screener({ cards }: { cards: Card[] }) {
  const [betsOnly, setBetsOnly] = useState(true);
  const [market, setMarket] = useState("");
  const [team, setTeam] = useState("");
  const [minEdge, setMinEdge] = useState(0);
  const [minConf, setMinConf] = useState(0);
  // bet requirement: "" = each market's backtested bar; a number overrides it for every market
  const [edgeReq, setEdgeReq] = useState<string>("");
  const [confReq, setConfReq] = useState(MIN_CONF);
  // Kelly settings (the paper-bet feed / Google Sheet always use the defaults so the record is reproducible)
  const [bankroll, setBankroll] = useState(DEFAULT_BANKROLL);
  const [fraction, setFraction] = useState<number>(DEFAULT_FRACTION);
  const [cap, setCap] = useState(MAX_STAKE_PCT * 100);
  const [exposure, setExposure] = useState(WEEKLY_EXPOSURE_PCT * 100);
  const [sort, setSort] = useState<SortKey>("score");
  const [open, setOpen] = useState<number | null>(null);
  // bets actually placed (logged to /api/placed; token lives in localStorage on this device only)
  const [token, setToken] = useState("");
  const [placed, setPlaced] = useState<Set<number>>(new Set());
  useEffect(() => {
    try { setToken(localStorage.getItem("placed_token") ?? ""); } catch {}
    fetch("/api/placed").then((r) => r.json()).then((d) => setPlaced(new Set((d.rows ?? []).map((r: { card_id: number }) => Number(r.card_id))))).catch(() => {});
  }, []);
  const togglePlaced = async (c: Card, stake: number) => {
    if (!token) { alert("Enter the placed-bets token in the settings panel first."); return; }
    const remove = placed.has(c.id);
    const r = await fetch("/api/placed", { method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ token, card_id: c.id, stake_units: stake, book: c.book, price_american: c.price_american, line: c.line, remove }) });
    if (!r.ok) { alert(r.status === 401 ? "Wrong token." : "Could not log the bet."); return; }
    setPlaced((p) => { const n = new Set(p); if (remove) n.delete(c.id); else n.add(c.id); return n; });
  };
  // Kelly is sized off the CALIBRATED probability when available — raw model edges overstate realised edge ~3×
  const pFor = (c: Card) => (c.prob_calibrated != null ? Number(c.prob_calibrated) : Number(c.model_prob));
  const stakeFor = (p: number, dec: number) => {
    const f = kellyFull(p, dec);
    if (f <= 0) return 0;
    const st = Math.round(Math.min(f * fraction, cap / 100) * bankroll * 20) / 20;
    return st >= 0.1 ? st : 0;
  };
  const clears = (c: Card) => Number(c.edge) >= (edgeReq === "" ? barFor(c.market) : Number(edgeReq) / 100) && c.confidence >= confReq;

  const markets = useMemo(() => [...new Set(cards.map((c) => c.market))], [cards]);
  const teams = useMemo(() => [...new Set(cards.flatMap((c) => [c.team, c.opponent]))].sort(), [cards]);

  // week-level exposure: scale every bet's stake by the same factor so the sum of the BETS stays within budget
  const scale = useMemo(() => exposureScale(cards.filter(clears).map((c) => stakeFor(pFor(c), Number(c.price_decimal))), bankroll, exposure / 100),
    [cards, edgeReq, confReq, bankroll, fraction, cap, exposure]);  // eslint-disable-line react-hooks/exhaustive-deps
  const rows = useMemo(() => cards
    .map((c) => ({ c, stake: Math.round(stakeFor(pFor(c), Number(c.price_decimal)) * scale * 20) / 20, isBet: clears(c) }))
    .filter(({ c, isBet }) => (!betsOnly || isBet) && (!market || c.market === market) && (!team || c.team === team || c.opponent === team)
      && Number(c.edge) * 100 >= minEdge && c.confidence >= minConf)
    .sort((a, b) =>
      sort === "kickoff" ? +new Date(a.c.kickoff_utc) - +new Date(b.c.kickoff_utc)
        : sort === "edge" ? Number(b.c.edge) - Number(a.c.edge)
        : sort === "confidence" ? b.c.confidence - a.c.confidence
        : sort === "stake" ? b.stake - a.stake
        : Number(b.c.score) - Number(a.c.score)), [cards, betsOnly, market, team, minEdge, minConf, sort, edgeReq, confReq, bankroll, fraction, cap, scale]);  // eslint-disable-line react-hooks/exhaustive-deps

  const betRows = rows.filter((r) => r.isBet);
  const total = betRows.reduce((s, r) => s + r.stake, 0);
  const expected = betRows.reduce((s, r) => s + r.stake * (pFor(r.c) * (Number(r.c.price_decimal) - 1) - (1 - pFor(r.c))), 0);
  const nBets = cards.filter(clears).length;
  const sel = "select";
  return (
    <div className="space-y-3">
      <div className="card flex min-w-0 flex-wrap items-end gap-x-4 gap-y-3 overflow-hidden p-4 text-[13px]">
        <div>
          <p className="eyebrow mb-1.5">What counts as a bet</p>
          <div className="flex flex-wrap items-end gap-2">
            <label className="flex flex-col gap-1 text-[12px] text-muted">Edge requirement
              <select className={sel} value={edgeReq} onChange={(e) => setEdgeReq(e.target.value)}>
                <option value="">{`Market bars — ${BARS_TEXT} (backtested)`}</option>
                {[4, 5, 6, 8, 10, 12, 15].map((v) => <option key={v} value={v}>≥ {v}% every market</option>)}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-[12px] text-muted">Min confidence
              <input type="number" className={`${sel} w-20`} value={confReq} min={0} max={100} onChange={(e) => setConfReq(+e.target.value)} />
            </label>
          </div>
        </div>
        <div>
          <p className="eyebrow mb-1.5">Stake sizing (Kelly)</p>
          <div className="flex flex-wrap items-end gap-2">
            <label className="flex flex-col gap-1 text-[12px] text-muted">Bankroll (units)
              <input type="number" className={`${sel} w-24`} value={bankroll} min={1} onChange={(e) => setBankroll(Math.max(1, +e.target.value))} />
            </label>
            <label className="flex flex-col gap-1 text-[12px] text-muted">Kelly fraction
              <select className={sel} value={fraction} onChange={(e) => setFraction(+e.target.value)}>
                {FRACTIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-[12px] text-muted">Cap per bet (% of bankroll)
              <input type="number" className={`${sel} w-20`} value={cap} min={0.5} max={25} step={0.5} onChange={(e) => setCap(+e.target.value)} />
            </label>
            <label className="flex flex-col gap-1 text-[12px] text-muted" title="Kelly sizes each bet against the whole bankroll; with many bets in one week the sum would exceed it. Stakes are scaled down together to fit this weekly budget.">Weekly exposure (% of bankroll)
              <input type="number" className={`${sel} w-20`} value={exposure} min={5} max={200} step={5} onChange={(e) => setExposure(+e.target.value)} />
            </label>
            <label className="flex flex-col gap-1 text-[12px] text-muted" title="Lets you mark rows as placed; those bets are tracked on the Track Record page at the price you took.">Placed-bets token
              <input type="password" className={`${sel} w-28`} value={token} placeholder="optional" onChange={(e) => { setToken(e.target.value); try { localStorage.setItem("placed_token", e.target.value); } catch {} }} />
            </label>
          </div>
        </div>
        <div className="grid w-full grid-cols-3 gap-2 text-center sm:ml-auto sm:w-auto">
          <div className="rounded-lg bg-panel-2/70 px-3 py-1.5"><div className="kpi-label">Bets</div><div className="text-lg font-semibold tnum">{nBets}</div></div>
          <div className="rounded-lg bg-panel-2/70 px-3 py-1.5"><div className="kpi-label">Staked</div><div className="text-lg font-semibold tnum">{total.toFixed(2)}u</div><div className="kpi-sub">{pct(total / bankroll, 1)} of bankroll{scale < 1 ? ` · scaled ×${scale.toFixed(2)}` : ""}</div></div>
          <div className="rounded-lg bg-panel-2/70 px-3 py-1.5"><div className="kpi-label">Expected</div><div className={`text-lg font-semibold tnum ${expected >= 0 ? "text-up" : "text-down"}`}>{expected >= 0 ? "+" : ""}{expected.toFixed(2)}u</div><div className="kpi-sub">if the model is right</div></div>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2 text-[13px]">
        <div className="flex rounded-lg border border-border bg-panel-2 p-0.5">
          <button onClick={() => setBetsOnly(true)} className={`rounded-md px-3 py-1.5 font-medium ${betsOnly ? "bg-panel-3 text-fg" : "text-muted"}`}>Bets ({nBets})</button>
          <button onClick={() => setBetsOnly(false)} className={`rounded-md px-3 py-1.5 font-medium ${!betsOnly ? "bg-panel-3 text-fg" : "text-muted"}`}>Everything priced ({cards.length})</button>
        </div>
        <select className={sel} value={market} onChange={(e) => setMarket(e.target.value)}>
          <option value="">All markets</option>
          {markets.map((m) => <option key={m} value={m}>{MARKET_NAMES[m] ?? m}</option>)}
        </select>
        <select className={sel} value={team} onChange={(e) => setTeam(e.target.value)}>
          <option value="">All teams</option>
          {teams.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
        {!betsOnly && (
          <>
            <label className="flex items-center gap-1 text-muted">Min edge <input type="number" className={`${sel} w-16`} value={minEdge} min={0} max={40} onChange={(e) => setMinEdge(+e.target.value)} />%</label>
            <label className="flex items-center gap-1 text-muted">Min conf <input type="number" className={`${sel} w-16`} value={minConf} min={0} max={100} onChange={(e) => setMinConf(+e.target.value)} /></label>
          </>
        )}
        <select className={`${sel} ml-auto`} value={sort} onChange={(e) => setSort(e.target.value as SortKey)}>
          <option value="score">Sort: edge × confidence</option>
          <option value="stake">Sort: stake</option>
          <option value="edge">Sort: edge</option>
          <option value="confidence">Sort: confidence</option>
          <option value="kickoff">Sort: kickoff</option>
        </select>
      </div>

      {rows.length === 0 ? (
        <div className="card p-8 text-center text-sm text-muted">Nothing matches. Switch to &ldquo;Everything priced&rdquo; to see every line the model evaluated.</div>
      ) : (
        <div className="card overflow-x-auto p-0">
          <table className="data text-[13px]">
            <thead><tr><th>Bet</th><th>Price</th><th>Model</th><th>Fair</th><th title="Model probability − fair probability. The publish bars are set on this number.">Edge</th><th title="What history says survives: a calibration model fit on ~16k graded bets shrinks the raw edge by situation. Kelly sizes off this.">Real edge</th><th>Conf</th><th title="Kelly on the calibrated probability">Stake</th><th>Kick</th><th></th></tr></thead>
            <tbody>
              {rows.map(({ c, stake, isBet }) => {
                const over = c.side === "Over";
                const isMl = c.market === "h2h";
                const top = c.factors.filter((f) => f.factor !== "projection" && f.impact !== "▬").slice(0, 3);
                return [
                  <tr key={c.id} className={`cursor-pointer ${isBet ? "" : "opacity-70"}`} onClick={() => setOpen(open === c.id ? null : c.id)}>
                    <td>
                      <div className="flex items-center gap-2">
                        <span className={`pill ${isMl ? "pill-accent" : over ? "pill-up" : "pill-down"}`}>{isMl ? "ML" : `${c.side === "Over" ? "O" : "U"} ${Number(c.line)}`}</span>
                        <span className="font-medium">{isMl ? c.team : c.player_name}</span>
                        <span className="text-muted">{MARKET_NAMES[c.market] ?? c.market} · {c.team} vs {c.opponent}</span>
                        {isBet && <span className="pill pill-up">bet</span>}
                      </div>
                    </td>
                    <td className="whitespace-nowrap">{american(c.price_american)} <span className="text-muted">{book(c.book)}</span></td>
                    <td>{pct(Number(c.model_prob), 1)}</td>
                    <td className="text-muted">{pct(Number(c.market_prob), 1)}</td>
                    <td className={`font-semibold ${isBet ? "text-up" : ""}`}>{signedPct(Number(c.edge))}</td>
                    <td className={c.edge_calibrated == null ? "text-dim" : Number(c.edge_calibrated) > 0 ? "text-up" : "text-down"}>{c.edge_calibrated == null ? "–" : signedPct(Number(c.edge_calibrated))}</td>
                    <td className={c.confidence >= confReq ? "" : "text-muted"}>{c.confidence}</td>
                    <td className="font-semibold">{isBet && stake > 0 ? `${stake.toFixed(2)}u` : <span className="text-dim">–</span>}</td>
                    <td className="whitespace-nowrap text-muted">{kickoff(c.kickoff_utc)}</td>
                    <td className="whitespace-nowrap">
                      {!isMl && token && (
                        <button onClick={(e) => { e.stopPropagation(); togglePlaced(c, stake); }} title={placed.has(c.id) ? "Logged as placed — click to remove" : "Log this bet as placed"}
                          className={`mr-2 rounded px-1.5 py-0.5 text-[11px] ${placed.has(c.id) ? "bg-up/20 text-up" : "bg-panel-2 text-muted hover:text-fg"}`}>{placed.has(c.id) ? "✓ placed" : "placed?"}</button>
                      )}
                      <Link href={c.href ?? `/cards/${c.id}`} className="text-accent hover:underline" onClick={(e) => e.stopPropagation()}>detail</Link>
                    </td>
                  </tr>,
                  open === c.id && (
                    <tr key={`${c.id}-why`} className="bg-panel-2/40">
                      <td colSpan={10} className="text-[12px]">
                        <ul className="space-y-1 py-1">
                          {top.map((f, i) => <li key={i}><span className={f.impact === "+" ? "text-up" : "text-down"}>{f.impact === "+" ? "▲" : "▼"}</span> {f.text}</li>)}
                          {c.factors.find((f) => f.factor === "projection") && <li className="text-muted">▬ {c.factors.find((f) => f.factor === "projection")!.text}</li>}
                        </ul>
                      </td>
                    </tr>
                  ),
                ];
              })}
            </tbody>
          </table>
        </div>
      )}
      <p className="text-[12px] text-dim">
        Edge = model probability − fair probability at the best price; the publish bars are set on it. Real edge = the same bet after a calibration model, fit on every graded bet (≈16k from the closing-line backtests plus every live result as it is graded), shrinks the raw edge by situation — on average only about a third of a raw edge survives the market. Confidence = the rule-based trust score (sample size, role stability, injury/weather data, line movement, sharp-book agreement).
        Stake = min(full Kelly × fraction, cap) × bankroll, then every bet is scaled by the same factor so the week&apos;s total stays within the exposure budget; rounded to 0.05u (under 0.1u shows as –). The paper-bet record and the Google Sheet always use the defaults (market bars, confidence 55, ¼-Kelly, 100u, 3% cap) so the track record stays reproducible; the settings above only change what you see here. Click a row for the reasons.
      </p>
    </div>
  );
}
