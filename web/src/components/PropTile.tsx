import Link from "next/link";
import type { Card } from "@/lib/queries";
import { american, book, kickoff, MARKET_NAMES } from "@/lib/format";
import { EdgeMeter } from "./EdgeMeter";

export function PropTile({ c, bar }: { c: Card; bar: number }) {
  const top = c.factors.filter((f) => f.factor !== "projection" && f.impact !== "▬").slice(0, 2);
  return (
    <Link href={`/cards/${c.id}`} className="block rounded-lg border border-border bg-panel p-3 hover:border-accent/60">
      <div className="flex items-baseline justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate font-semibold">{c.player_name} <span className="text-xs font-normal text-muted">{c.team} vs {c.opponent}</span></div>
          <div className="text-sm">
            <span className="text-muted">{MARKET_NAMES[c.market] ?? c.market}</span>{" "}
            <span className={c.side === "Over" ? "text-up" : "text-down"}>{c.side.toUpperCase()} {Number(c.line)}</span>
            <span className="ml-1.5 text-xs text-muted tnum">{american(c.price_american)} {book(c.book)}</span>
          </div>
        </div>
        <div className="shrink-0 text-right text-[11px] text-muted"><div className="text-lg font-semibold text-fg tnum">{c.confidence}</div>conf</div>
      </div>
      <div className="mt-2"><EdgeMeter edge={Number(c.edge)} bar={bar} /></div>
      <ul className="mt-2 space-y-0.5 text-xs text-muted">
        {top.map((f, i) => <li key={i} className="truncate"><span className={f.impact === "+" ? "text-up" : "text-down"}>{f.impact === "+" ? "▲" : "▼"}</span> {f.text}</li>)}
      </ul>
      <div className="mt-1.5 text-[11px] text-muted">{kickoff(c.kickoff_utc)}</div>
    </Link>
  );
}
