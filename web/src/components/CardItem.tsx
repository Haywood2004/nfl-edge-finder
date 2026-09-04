import Link from "next/link";
import type { Card } from "@/lib/queries";
import { american, book, kickoff, MARKET_NAMES, num, pct, signedPct } from "@/lib/format";
import { FactorList } from "./FactorList";

export function CardItem({ c }: { c: Card }) {
  const over = c.side === "Over";
  const matchup = c.team === c.home_team ? `${c.opponent} @ ${c.team}` : `${c.team} @ ${c.opponent}`;
  const proj = c.factors.find((f) => f.factor === "projection");
  const isMl = c.market === "h2h";
  return (
    <article className={`card p-4 sm:p-5 ${c.published ? "ring-1 ring-up/30" : ""}`}>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1.5">
        <span className="rounded-md bg-panel-2 px-1.5 py-0.5 text-[11px] font-semibold tracking-wider text-muted">{c.position}</span>
        <h3 className="text-[15px] font-semibold tracking-tight">
          <Link href={`/cards/${c.id}`} className="hover:underline">{isMl ? c.team : c.player_name}</Link>
        </h3>
        <span className="text-[13px] text-muted">{MARKET_NAMES[c.market] ?? c.market}</span>
        <span className={`pill ${over ? "pill-up" : isMl ? "pill-accent" : "pill-down"}`}>{isMl ? "TO WIN" : `${c.side.toUpperCase()} ${Number(c.line)}`}</span>
        <span className="ml-auto text-[12px]">
          {c.published ? <span className="pill pill-up">Flagged</span> : <span className="pill">paper · below bar</span>}
          {c.published && c.trend_badges?.length > 0 && <span className="pill pill-accent ml-1">Model + Trend</span>}
        </span>
      </div>
      <p className="mt-1 text-[12px] text-muted">{matchup} · {kickoff(c.kickoff_utc)} · best price <span className="text-fg-2 tnum">{american(c.price_american)}</span> {book(c.book)}</p>
      <div className="mt-3 grid grid-cols-4 gap-1.5 text-center">
        <Stat label="Edge" value={signedPct(Number(c.edge))} strong up={Number(c.edge) >= 0.15} />
        <Stat label="Model" value={pct(Number(c.model_prob))} />
        <Stat label="Market" value={pct(Number(c.market_prob))} />
        <Stat label="Conf" value={String(c.confidence)} />
      </div>
      {proj && <p className="mt-2 text-[12px] text-muted">{proj.text}</p>}
      <div className="mt-3 border-t border-border/60 pt-3">
        <p className="eyebrow mb-1.5">Why</p>
        <FactorList factors={c.factors.filter((f) => f.factor !== "projection")} season={c.season} week={c.week} limit={5} />
      </div>
      <div className="mt-3 flex items-center justify-between text-[12px] text-muted">
        <span>EV {num(Number(c.ev_per_unit) * 100, 1)}¢ per $1 · {c.book_prices.length} venues</span>
        <Link href={`/cards/${c.id}`} className="text-accent hover:underline">Full detail →</Link>
      </div>
    </article>
  );
}

function Stat({ label, value, strong, up }: { label: string; value: string; strong?: boolean; up?: boolean }) {
  return (
    <div className="rounded-lg bg-panel-2/70 px-2 py-1.5">
      <div className="text-[10px] font-semibold uppercase tracking-wider text-dim">{label}</div>
      <div className={`text-[14px] tnum ${strong ? "font-semibold" : ""} ${up ? "text-up" : ""}`}>{value}</div>
    </div>
  );
}
