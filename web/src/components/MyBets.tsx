"use client";
import { useEffect, useMemo, useState } from "react";
import { american, book, MARKET_NAMES, signedPct } from "@/lib/format";
import { getToken, login } from "@/lib/auth";

type Row = { id: number; placed_at: string; stake_units: string; book: string | null; price_american: number | null; line: string | null; note: string | null;
  card_id: number; player_name: string; market: string; side: string; team: string; opponent: string; kickoff_utc: string; season: number; week: number;
  edge: string; edge_calibrated: string | null; result: string | null; actual: string | null; profit_units: string | null; clv_prob: string | null };
type Cand = { card_id: number; season: number; week: number; player_name: string; team: string; opponent: string; market: string; side: string; line: string;
  book: string; price_american: number; kickoff_utc: string; edge: string; edge_calibrated: string | null; result: string | null; actual: string | null; suggested_stake: number };

const kick = (s: string) => new Date(s).toLocaleString("en-US", { timeZone: "America/New_York", weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
const pnl = (r: Row) => (r.profit_units == null ? null : Number(r.profit_units) * Number(r.stake_units));

/** Your own ledger: every bet you logged, graded at your price and stake. Logged-in: log past picks too. */
export function MyBets() {
  const [rows, setRows] = useState<Row[]>([]);
  const [token, setToken] = useState("");
  const [cands, setCands] = useState<Cand[]>([]);
  const [q, setQ] = useState("");
  const [stakes, setStakes] = useState<Record<number, string>>({});
  const [prices, setPrices] = useState<Record<number, string>>({});
  const load = () => fetch("/api/placed").then((r) => r.json()).then((d) => setRows(d.rows ?? [])).catch(() => {});
  useEffect(() => {
    load();
    setToken(getToken());
    const h = (e: Event) => setToken(String((e as CustomEvent).detail ?? ""));
    window.addEventListener("placed-token", h);
    return () => window.removeEventListener("placed-token", h);
  }, []);
  useEffect(() => {
    if (token) fetch("/api/placed?candidates=1").then((r) => r.json()).then((d) => setCands(d.rows ?? [])).catch(() => {});
  }, [token]);

  const graded = rows.filter((r) => r.result === "win" || r.result === "loss");
  const w = rows.filter((r) => r.result === "win").length, l = rows.filter((r) => r.result === "loss").length;
  const pv = rows.filter((r) => r.result === "push" || r.result === "void").length;
  const staked = graded.reduce((s, r) => s + Number(r.stake_units), 0);
  const units = rows.reduce((s, r) => s + (pnl(r) ?? 0), 0);
  const open = rows.filter((r) => !r.result).reduce((s, r) => s + Number(r.stake_units), 0);
  const clvs = rows.filter((r) => r.clv_prob != null).map((r) => Number(r.clv_prob));
  const clv = clvs.length ? clvs.reduce((a, b) => a + b, 0) / clvs.length : null;
  const placedIds = useMemo(() => new Set(rows.map((r) => r.card_id)), [rows]);
  const shown = useMemo(() => {
    const t = q.trim().toLowerCase();
    return cands.filter((c) => !placedIds.has(c.card_id) && (!t || `${c.player_name} ${c.team} ${c.opponent} ${MARKET_NAMES[c.market] ?? ""}`.toLowerCase().includes(t)))
      .sort((a, b) => +new Date(b.kickoff_utc) - +new Date(a.kickoff_utc)).slice(0, 40);
  }, [cands, q, placedIds]);

  const post = async (body: Record<string, unknown>) => {
    const tk = token || getToken();
    if (!tk) { if (!(await login())) return false; }
    const r = await fetch("/api/placed", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ token: tk || getToken(), ...body }) });
    if (!r.ok) { alert(r.status === 401 ? "Wrong password — log in again." : "Could not save."); return false; }
    await load();
    return true;
  };
  const add = (c: Cand) => post({ card_id: c.card_id, stake_units: Number(stakes[c.card_id] ?? (c.suggested_stake || 1)) || 1, book: c.book,
    price_american: prices[c.card_id] ? Number(prices[c.card_id]) : c.price_american, line: c.line });
  const remove = (r: Row) => { if (confirm(`Remove ${r.player_name} ${r.side} ${r.line}?`)) post({ card_id: r.card_id, remove: true }); };

  const kpi = (label: string, value: string, sub?: string, tone?: "up" | "down") => (
    <div className="card kpi min-w-0"><div className="kpi-label">{label}</div><div className={`kpi-value ${tone === "up" ? "text-up" : tone === "down" ? "text-down" : ""}`}>{value}</div>{sub && <div className="kpi-sub">{sub}</div>}</div>
  );

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
        {kpi("Record", `${w}-${l}${pv ? `-${pv}` : ""}`, `${rows.length} bets logged`)}
        {kpi("Win rate", w + l ? `${(100 * w / (w + l)).toFixed(1)}%` : "–")}
        {kpi("Units", `${units >= 0 ? "+" : ""}${units.toFixed(2)}u`, `${staked.toFixed(2)}u settled${open ? ` · ${open.toFixed(2)}u open` : ""}`, units >= 0 ? "up" : "down")}
        {kpi("ROI", staked ? signedPct(units / staked) : "–", "on settled stakes")}
        {kpi("Avg CLV", clv == null ? "–" : signedPct(clv), "closing-line value")}
      </div>

      <section className="card p-0">
        {rows.length === 0 ? (
          <p className="p-6 text-sm text-muted">No bets logged yet. Log in (top right), then use &ldquo;placed?&rdquo; on the screener or the form below.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="data text-[13px]">
              <thead><tr><th>Bet</th><th>Price</th><th>Stake</th><th>Kick</th><th>Actual</th><th>Result</th><th>P&amp;L</th><th>CLV</th>{token && <th></th>}</tr></thead>
              <tbody>
                {rows.map((r) => {
                  const p = pnl(r);
                  return (
                    <tr key={r.id}>
                      <td><span className={`pill ${r.side === "Over" ? "pill-up" : "pill-down"}`}>{r.side === "Over" ? "O" : "U"} {Number(r.line)}</span> <span className="font-medium">{r.player_name}</span> <span className="text-muted">{MARKET_NAMES[r.market] ?? r.market} · {r.team} vs {r.opponent}</span></td>
                      <td className="whitespace-nowrap">{r.price_american != null ? american(r.price_american) : "–"} <span className="text-muted">{book(r.book ?? "")}</span></td>
                      <td>{Number(r.stake_units).toFixed(2)}u</td>
                      <td className="whitespace-nowrap text-muted">{kick(r.kickoff_utc)}</td>
                      <td>{r.actual == null ? <span className="text-dim">pending</span> : Number(r.actual).toFixed(0)}</td>
                      <td className={r.result === "win" ? "text-up" : r.result === "loss" ? "text-down" : "text-muted"}>{r.result ?? "–"}</td>
                      <td className={p == null ? "text-dim" : p >= 0 ? "text-up" : "text-down"}>{p == null ? "–" : `${p >= 0 ? "+" : ""}${p.toFixed(2)}u`}</td>
                      <td className="text-muted">{r.clv_prob == null ? "–" : signedPct(Number(r.clv_prob))}</td>
                      {token && <td><button onClick={() => remove(r)} className="text-[11px] text-muted hover:text-down">remove</button></td>}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {token && (
        <section className="card p-4 sm:p-5">
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <h2 className="eyebrow">Log a bet</h2>
            <input className="select w-64" placeholder="Search player / team…" value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
          <p className="mb-3 text-[12px] text-muted">Every pick the model priced in the last two weeks (≥4% edge), one row per pick. The stake defaults to the model's Kelly size (what the screener showed); change it or the price if you bet differently, then log it. Graded picks fill in immediately.</p>
          <div className="overflow-x-auto">
            <table className="data text-[13px]">
              <thead><tr><th>Pick</th><th>Best price</th><th>Kick</th><th>Result</th><th>Stake (u)</th><th>Your price</th><th></th></tr></thead>
              <tbody>
                {shown.map((c) => (
                  <tr key={c.card_id}>
                    <td><span className={`pill ${c.side === "Over" ? "pill-up" : "pill-down"}`}>{c.side === "Over" ? "O" : "U"} {Number(c.line)}</span> <span className="font-medium">{c.player_name}</span> <span className="text-muted">{MARKET_NAMES[c.market] ?? c.market} · {c.team} vs {c.opponent}</span></td>
                    <td className="whitespace-nowrap">{american(c.price_american)} <span className="text-muted">{book(c.book)}</span></td>
                    <td className="whitespace-nowrap text-muted">{kick(c.kickoff_utc)}</td>
                    <td className={c.result === "win" ? "text-up" : c.result === "loss" ? "text-down" : "text-muted"}>{c.result ?? "pending"}{c.actual != null ? ` (${Number(c.actual).toFixed(0)})` : ""}</td>
                    <td><input type="number" step={0.05} min={0.05} className="select w-20" placeholder={c.suggested_stake ? c.suggested_stake.toFixed(2) : "1.00"} value={stakes[c.card_id] ?? ""} onChange={(e) => setStakes({ ...stakes, [c.card_id]: e.target.value })} /></td>
                    <td><input type="number" step={1} className="select w-20" placeholder={String(c.price_american)} value={prices[c.card_id] ?? ""} onChange={(e) => setPrices({ ...prices, [c.card_id]: e.target.value })} /></td>
                    <td><button onClick={() => add(c)} className="rounded bg-panel-2 px-2 py-0.5 text-[12px] hover:text-fg">log</button></td>
                  </tr>
                ))}
                {shown.length === 0 && <tr><td colSpan={7} className="py-3 text-muted">Nothing matches.</td></tr>}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
}
