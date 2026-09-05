"use client";
import { useMemo, useState } from "react";
import Link from "next/link";
import type { Card } from "@/lib/queries";
import { american, book, kickoff, MARKET_NAMES, pct, signedPct } from "@/lib/format";
import { barFor, MIN_CONF } from "@/lib/thresholds";
import { kellyStake, DEFAULT_BANKROLL, DEFAULT_FRACTION } from "@/lib/kelly";

type SortKey = "score" | "edge" | "confidence" | "stake" | "kickoff";

/** One table for everything the model priced this week. Default view = the bets (each market's bar + confidence ≥ 55). */
export function Screener({ cards }: { cards: Card[] }) {
  const [betsOnly, setBetsOnly] = useState(true);
  const [market, setMarket] = useState("");
  const [team, setTeam] = useState("");
  const [minEdge, setMinEdge] = useState(0);
  const [minConf, setMinConf] = useState(0);
  const [sort, setSort] = useState<SortKey>("score");
  const [open, setOpen] = useState<number | null>(null);

  const markets = useMemo(() => [...new Set(cards.map((c) => c.market))], [cards]);
  const teams = useMemo(() => [...new Set(cards.flatMap((c) => [c.team, c.opponent]))].sort(), [cards]);

  const rows = useMemo(() => cards
    .map((c) => ({ c, stake: kellyStake(Number(c.model_prob), Number(c.price_decimal), DEFAULT_BANKROLL, DEFAULT_FRACTION),
      isBet: Number(c.edge) >= barFor(c.market) && c.confidence >= MIN_CONF }))
    .filter(({ c, isBet }) => (!betsOnly || isBet) && (!market || c.market === market) && (!team || c.team === team || c.opponent === team)
      && Number(c.edge) * 100 >= minEdge && c.confidence >= minConf)
    .sort((a, b) =>
      sort === "kickoff" ? +new Date(a.c.kickoff_utc) - +new Date(b.c.kickoff_utc)
        : sort === "edge" ? Number(b.c.edge) - Number(a.c.edge)
        : sort === "confidence" ? b.c.confidence - a.c.confidence
        : sort === "stake" ? b.stake - a.stake
        : Number(b.c.score) - Number(a.c.score)), [cards, betsOnly, market, team, minEdge, minConf, sort]);

  const total = rows.filter((r) => r.isBet).reduce((s, r) => s + r.stake, 0);
  const sel = "select";
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-[13px]">
        <div className="flex rounded-lg border border-border bg-panel-2 p-0.5">
          <button onClick={() => setBetsOnly(true)} className={`rounded-md px-3 py-1.5 font-medium ${betsOnly ? "bg-panel-3 text-fg" : "text-muted"}`}>Bets ({cards.filter((c) => Number(c.edge) >= barFor(c.market) && c.confidence >= MIN_CONF).length})</button>
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
            <thead><tr><th>Bet</th><th>Price</th><th>Model</th><th>Fair</th><th>Edge</th><th>Conf</th><th title="¼-Kelly on a 100-unit bankroll, capped at 3%">Stake</th><th>Kick</th><th></th></tr></thead>
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
                    <td className={c.confidence >= MIN_CONF ? "" : "text-muted"}>{c.confidence}</td>
                    <td className="font-semibold">{isBet && stake > 0 ? `${stake.toFixed(2)}u` : <span className="text-dim">–</span>}</td>
                    <td className="whitespace-nowrap text-muted">{kickoff(c.kickoff_utc)}</td>
                    <td><Link href={c.href ?? `/cards/${c.id}`} className="text-accent hover:underline" onClick={(e) => e.stopPropagation()}>detail</Link></td>
                  </tr>,
                  open === c.id && (
                    <tr key={`${c.id}-why`} className="bg-panel-2/40">
                      <td colSpan={9} className="text-[12px]">
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
        {betsOnly ? `${rows.length} bets · ${total.toFixed(2)}u total at ¼-Kelly on 100u. ` : ""}
        Edge = model probability − fair probability at the best price. Confidence = how much to trust that edge (sample size, role stability, injury/weather data, line movement). Stake = ¼-Kelly on a 100u bankroll, capped at 3% per bet — <Link href="/kelly" className="text-accent hover:underline">change bankroll or fraction</Link>. Click a row for the reasons.
      </p>
    </div>
  );
}
