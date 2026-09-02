import Link from "next/link";
import type { Card } from "@/lib/queries";
import { american, book, kickoff, MARKET_NAMES, num, pct, signedPct } from "@/lib/format";
import { FactorList } from "./FactorList";

export function CardItem({ c }: { c: Card }) {
  const sideCls = c.side === "Over" ? "text-up" : "text-down";
  const matchup = c.team === c.home_team ? `${c.opponent} @ ${c.team}` : `${c.team} @ ${c.opponent}`;
  const proj = c.factors.find((f) => f.factor === "projection");
  return (
    <article className={`rounded-lg border bg-panel p-4 ${c.published ? "border-border" : "border-border/60 opacity-90"}`}>
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <span className="rounded bg-panel-2 px-1.5 py-0.5 text-xs font-medium text-muted">{c.position}</span>
        <h3 className="text-base font-semibold">
          {MARKET_NAMES[c.market] ?? c.market} <span className={sideCls}>{c.side.toUpperCase()} {Number(c.line)}</span>
        </h3>
        <span className="text-sm text-muted tnum">({american(c.price_american)} {book(c.book)}, best)</span>
        {!c.published && <span className="ml-auto rounded border border-warn/40 px-1.5 py-0.5 text-[11px] text-warn">below threshold</span>}
        {c.published && c.trend_badges?.length > 0 && <span className="ml-auto rounded bg-accent/20 px-1.5 py-0.5 text-[11px] text-accent">Model + Trend</span>}
      </div>
      <p className="mt-0.5 text-sm text-muted">
        <Link href={`/cards/${c.id}`} className="text-fg hover:underline">{c.player_name}</Link> · {matchup} · {kickoff(c.kickoff_utc)}
      </p>
      <div className="mt-3 grid grid-cols-4 gap-2 text-center text-sm tnum">
        <Stat label="Edge" value={signedPct(Number(c.edge))} strong />
        <Stat label="Model" value={pct(Number(c.model_prob))} />
        <Stat label="Market" value={pct(Number(c.market_prob))} />
        <Stat label="Confidence" value={String(c.confidence)} />
      </div>
      {proj && <p className="mt-2 text-xs text-muted">{proj.text}</p>}
      <div className="mt-3">
        <p className="mb-1 text-xs font-medium uppercase tracking-wide text-muted">Why</p>
        <FactorList factors={c.factors.filter((f) => f.factor !== "projection")} season={c.season} week={c.week} limit={5} />
      </div>
      <div className="mt-3 flex items-center justify-between text-xs text-muted">
        <span>EV {num(Number(c.ev_per_unit) * 100, 1)}¢ per $1 · {c.book_prices.length} books</span>
        <Link href={`/cards/${c.id}`} className="text-accent hover:underline">Full detail →</Link>
      </div>
    </article>
  );
}

function Stat({ label, value, strong }: { label: string; value: string; strong?: boolean }) {
  return (
    <div className="rounded bg-panel-2 px-2 py-1.5">
      <div className="text-[11px] uppercase tracking-wide text-muted">{label}</div>
      <div className={strong ? "font-semibold" : ""}>{value}</div>
    </div>
  );
}
