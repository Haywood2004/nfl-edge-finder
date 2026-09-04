import Link from "next/link";
import type { Card } from "@/lib/queries";
import { american, book, kickoff, MARKET_NAMES } from "@/lib/format";
import { EdgeMeter } from "./EdgeMeter";

export function PropTile({ c, bar }: { c: Card; bar: number }) {
  const top = c.factors.filter((f) => f.factor !== "projection" && f.impact !== "▬").slice(0, 2);
  const over = c.side === "Over";
  const clears = Number(c.edge) >= bar && c.confidence >= 55;
  return (
    <Link href={`/cards/${c.id}`} className={`card card-hover block min-w-0 overflow-hidden p-4 ${clears ? "ring-1 ring-up/40" : ""}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate text-[15px] font-semibold tracking-tight">{c.player_name}</div>
          <div className="mt-0.5 text-[12px] text-muted">{c.team} vs {c.opponent} · {kickoff(c.kickoff_utc)}</div>
        </div>
        <div className="shrink-0 text-right">
          <div className="text-[11px] uppercase tracking-wider text-dim">Conf</div>
          <div className="text-lg font-semibold leading-tight tnum">{c.confidence}</div>
        </div>
      </div>
      <div className="mt-3 flex items-center gap-2">
        <span className={`pill ${over ? "pill-up" : "pill-down"}`}>{c.side.toUpperCase()} {Number(c.line)}</span>
        <span className="text-[12px] text-muted">{MARKET_NAMES[c.market] ?? c.market}</span>
        <span className="ml-auto text-[12px] text-fg-2 tnum">{american(c.price_american)} <span className="text-muted">{book(c.book)}</span></span>
      </div>
      <div className="mt-3"><EdgeMeter edge={Number(c.edge)} bar={bar} width={999} /></div>
      {top.length > 0 && (
        <ul className="mt-3 space-y-1 border-t border-border/60 pt-2.5 text-[12px] leading-snug text-muted">
          {top.map((f, i) => <li key={i} className="truncate"><span className={f.impact === "+" ? "text-up" : "text-down"}>{f.impact === "+" ? "▲" : "▼"}</span> {f.text}</li>)}
        </ul>
      )}
    </Link>
  );
}
