"use client";
import { useMemo, useState } from "react";
import type { Card } from "@/lib/queries";
import { CardItem } from "./CardItem";
import { book, MARKET_NAMES } from "@/lib/format";

export function Feed({ cards, showAll }: { cards: Card[]; showAll: boolean }) {
  const [market, setMarket] = useState("");
  const [team, setTeam] = useState("");
  const [bk, setBk] = useState("");
  const [minEdge, setMinEdge] = useState(showAll ? 0 : 15);
  const [minConf, setMinConf] = useState(showAll ? 0 : 55);
  const [sort, setSort] = useState<"score" | "edge" | "confidence" | "kickoff">("score");

  const markets = useMemo(() => [...new Set(cards.map((c) => c.market))], [cards]);
  const teams = useMemo(() => [...new Set(cards.flatMap((c) => [c.team, c.opponent]))].sort(), [cards]);
  const books = useMemo(() => [...new Set(cards.map((c) => c.book))].sort(), [cards]);

  const list = cards
    .filter((c) => (!market || c.market === market) && (!team || c.team === team || c.opponent === team) && (!bk || c.book === bk))
    .filter((c) => Number(c.edge) * 100 >= minEdge && c.confidence >= minConf)
    .sort((a, b) =>
      sort === "kickoff" ? +new Date(a.kickoff_utc) - +new Date(b.kickoff_utc)
        : sort === "edge" ? Number(b.edge) - Number(a.edge)
        : sort === "confidence" ? b.confidence - a.confidence
        : Number(b.score) - Number(a.score));

  const sel = "rounded border border-border bg-panel px-2 py-1.5 text-sm";
  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-2 text-sm">
        <select className={sel} value={market} onChange={(e) => setMarket(e.target.value)}>
          <option value="">All markets</option>
          {markets.map((m) => <option key={m} value={m}>{MARKET_NAMES[m] ?? m}</option>)}
        </select>
        <select className={sel} value={team} onChange={(e) => setTeam(e.target.value)}>
          <option value="">All teams</option>
          {teams.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
        <select className={sel} value={bk} onChange={(e) => setBk(e.target.value)}>
          <option value="">All books</option>
          {books.map((b) => <option key={b} value={b}>{book(b)}</option>)}
        </select>
        <label className="flex items-center gap-1 text-muted">Min edge
          <input type="number" className={`${sel} w-16`} value={minEdge} min={0} max={30} onChange={(e) => setMinEdge(+e.target.value)} />%
        </label>
        <label className="flex items-center gap-1 text-muted">Min conf
          <input type="number" className={`${sel} w-16`} value={minConf} min={0} max={100} onChange={(e) => setMinConf(+e.target.value)} />
        </label>
        <select className={`${sel} ml-auto`} value={sort} onChange={(e) => setSort(e.target.value as typeof sort)}>
          <option value="score">Sort: edge × confidence</option>
          <option value="edge">Sort: edge</option>
          <option value="confidence">Sort: confidence</option>
          <option value="kickoff">Sort: kickoff</option>
        </select>
      </div>
      {list.length === 0 ? (
        <p className="rounded-lg border border-border bg-panel p-6 text-center text-sm text-muted">
          No cards match. Lower the thresholds, or check the <a href="/board" className="text-accent">full board</a>.
        </p>
      ) : (
        <div className="grid gap-3 md:grid-cols-2">{list.map((c) => <CardItem key={c.id} c={c} />)}</div>
      )}
      <p className="mt-3 text-xs text-muted">{list.length} of {cards.length} cards shown.</p>
    </div>
  );
}
