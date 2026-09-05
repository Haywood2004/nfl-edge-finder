"use client";
import { useMemo, useState } from "react";
import Link from "next/link";
import type { Card } from "@/lib/queries";
import { american, book, kickoff, MARKET_NAMES, pct, signedPct } from "@/lib/format";
import { kellyFull, kellyStake, DEFAULT_BANKROLL, DEFAULT_FRACTION, MAX_STAKE_PCT } from "@/lib/kelly";
import { barFor } from "@/lib/thresholds";

const FRACTIONS = [[1, "Full Kelly"], [0.5, "Half"], [0.25, "Quarter (default)"], [0.125, "Eighth"]] as const;

export function KellyTable({ cards }: { cards: Card[] }) {
  const [bankroll, setBankroll] = useState(DEFAULT_BANKROLL);
  const [fraction, setFraction] = useState<number>(DEFAULT_FRACTION);
  const [minEdge, setMinEdge] = useState(0);
  const [betsOnly, setBetsOnly] = useState(true);
  const [minConf, setMinConf] = useState(55);
  const [cap, setCap] = useState(MAX_STAKE_PCT * 100);

  const rows = useMemo(() => {
    return cards
      .filter((c) => (!betsOnly || (Number(c.edge) >= barFor(c.market) && c.confidence >= 55)) && Number(c.edge) * 100 >= minEdge && c.confidence >= minConf)
      .map((c) => {
        const p = Number(c.model_prob), dec = Number(c.price_decimal);
        const full = kellyFull(p, dec);
        const stake = Math.min(Math.round(Math.min(full * fraction, cap / 100) * bankroll * 4) / 4, bankroll);
        return { c, p, dec, full, stake: stake >= 0.25 ? stake : 0, ev: p * (dec - 1) - (1 - p) };
      })
      .filter((r) => r.full > 0)
      .sort((a, b) => b.stake - a.stake || b.full - a.full);
  }, [cards, betsOnly, minEdge, minConf, fraction, bankroll, cap]);

  const total = rows.reduce((s, r) => s + r.stake, 0);
  const expected = rows.reduce((s, r) => s + r.stake * r.ev, 0);
  const sel = "select";
  return (
    <div className="space-y-4">
      <div className="card flex flex-wrap items-end gap-3 p-4 text-sm">
        <label className="flex flex-col gap-1 text-[12px] text-muted">Bankroll (units)
          <input type="number" className={`${sel} w-24`} value={bankroll} min={1} onChange={(e) => setBankroll(Math.max(1, +e.target.value))} />
        </label>
        <label className="flex flex-col gap-1 text-[12px] text-muted">Kelly fraction
          <select className={sel} value={fraction} onChange={(e) => setFraction(+e.target.value)}>
            {FRACTIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-[12px] text-muted">Cap per bet (% bankroll)
          <input type="number" className={`${sel} w-20`} value={cap} min={0.5} max={25} step={0.5} onChange={(e) => setCap(+e.target.value)} />
        </label>
        <label className="flex flex-col gap-1 text-[12px] text-muted">Which bets
          <select className={sel} value={betsOnly ? "bets" : "all"} onChange={(e) => setBetsOnly(e.target.value === "bets")}>
            <option value="bets">Bets only (same as screener)</option>
            <option value="all">Everything priced</option>
          </select>
        </label>
        <label className="flex flex-col gap-1 text-[12px] text-muted">Min edge %
          <input type="number" className={`${sel} w-20`} value={minEdge} min={0} max={30} onChange={(e) => setMinEdge(+e.target.value)} />
        </label>
        <label className="flex flex-col gap-1 text-[12px] text-muted">Min confidence
          <input type="number" className={`${sel} w-20`} value={minConf} min={0} max={100} onChange={(e) => setMinConf(+e.target.value)} />
        </label>
      </div>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Kpi label="Bets sized" value={String(rows.filter((r) => r.stake > 0).length)} sub={`of ${rows.length} with positive Kelly`} />
        <Kpi label="Total staked" value={`${total.toFixed(2)}u`} sub={`${pct(total / bankroll, 1)} of bankroll`} />
        <Kpi label="Expected profit" value={`${expected >= 0 ? "+" : ""}${expected.toFixed(2)}u`} sub="if model probabilities are right" />
        <Kpi label="Largest stake" value={rows[0] ? `${rows[0].stake.toFixed(2)}u` : "–"} sub={rows[0] ? (rows[0].c.market === "h2h" ? `${rows[0].c.team} ML` : `${rows[0].c.player_name} ${rows[0].c.side}`) : ""} />
      </div>

      {rows.length === 0 ? (
        <div className="card p-8 text-center text-sm text-muted">No bets clear these filters with a positive Kelly fraction.</div>
      ) : (
        <div className="card overflow-x-auto p-0">
          <table className="data text-[13px]">
            <thead><tr>{["Bet", "Price", "Model p", "Fair p", "Edge", "EV / $1", "Full Kelly", "Stake", "Kick"].map((h) => <th key={h}>{h}</th>)}</tr></thead>
            <tbody>
              {rows.map(({ c, p, full, stake, ev }) => (
                <tr key={`${c.id}-${c.side}`} className={stake === 0 ? "opacity-50" : ""}>
                  <td>
                    <Link href={c.href ?? `/cards/${c.id}`} className="font-medium hover:underline">{c.market === "h2h" ? `${c.team} to win` : `${c.player_name} ${c.side} ${Number(c.line)}`}</Link>
                    <span className="ml-1.5 text-muted">{MARKET_NAMES[c.market] ?? c.market}</span>
                    {c.published && <span className="pill pill-up ml-1.5">flagged</span>}
                  </td>
                  <td>{american(c.price_american)} <span className="text-muted">{book(c.book)}</span></td>
                  <td>{pct(p, 1)}</td><td className="text-muted">{pct(Number(c.market_prob), 1)}</td>
                  <td className={Number(c.edge) >= barFor(c.market) ? "text-up" : ""}>{signedPct(Number(c.edge))}</td>
                  <td>{(ev * 100).toFixed(1)}¢</td>
                  <td>{pct(full, 1)}</td>
                  <td className={`font-semibold ${stake > 0 ? "text-fg" : "text-muted"}`}>{stake > 0 ? `${stake.toFixed(2)}u` : "skip"}</td>
                  <td className="text-muted whitespace-nowrap">{kickoff(c.kickoff_utc)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="text-[12px] text-dim">
        Stake = min(full Kelly × fraction, cap) × bankroll, rounded to ¼ unit; anything under ¼u is skipped. Kelly assumes bets are independent and the probability is right — correlated legs (same game, same QB) and model error both argue for a smaller fraction, not a larger one.
      </p>
    </div>
  );
}

function Kpi({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="card kpi"><div className="kpi-label">{label}</div><div className="kpi-value">{value}</div>{sub && <div className="kpi-sub">{sub}</div>}</div>
  );
}
