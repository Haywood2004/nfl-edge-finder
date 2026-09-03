import Link from "next/link";
import { latestCards, latestGameProjections } from "@/lib/queries";
import { Freshness } from "@/components/Freshness";
import { GameTile, GameLegend } from "@/components/GameTile";
import { PropTile } from "@/components/PropTile";
import { EdgeMeter } from "@/components/EdgeMeter";

export const dynamic = "force-dynamic";
const BAR = 0.15;

export default async function Home() {
  const [cards, games] = await Promise.all([latestCards(), latestGameProjections()]);
  const wk = cards[0] ?? games[0];
  const props = cards.filter((c) => c.market !== "h2h");
  const mls = cards.filter((c) => c.market === "h2h");
  const clears = cards.filter((c) => Number(c.edge) >= BAR && c.confidence >= 55);
  const closest = [...cards].sort((a, b) => Number(b.edge) - Number(a.edge)).slice(0, 3);
  const maxEdge = closest[0] ? Number(closest[0].edge) : 0;

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <h1 className="text-2xl font-semibold">{wk ? `${wk.season} · Week ${wk.week}` : "This Week"}</h1>
        <Freshness />
      </div>

      {/* Hero: edges that clear the bar */}
      <section className="rounded-xl border border-border bg-panel p-5">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-lg font-semibold">Edges ≥ {Math.round(BAR * 100)}%</h2>
          <span className="text-xs text-muted">{cards.length} bets priced · {props.length} props · {mls.length} moneyline</span>
        </div>
        {clears.length ? (
          <div className="mt-3 grid gap-3 md:grid-cols-2">{clears.map((c) => <PropTile key={c.id} c={c} bar={BAR} />)}</div>
        ) : (
          <div className="mt-3 grid gap-4 md:grid-cols-[1fr_auto] md:items-center">
            <div className="min-w-0">
              <p className="text-3xl font-semibold tnum">0 <span className="text-base font-normal text-muted">this week</span></p>
              <p className="mt-1 text-sm text-muted">Biggest edge on the board is {(maxEdge * 100).toFixed(1)}%. The bar is deliberately high: in NFL markets a claimed 15% gap is usually the model being wrong, not the book. Everything is still priced below.</p>
            </div>
            <div className="min-w-0 space-y-2 text-sm">
              {closest.map((c) => (
                <Link key={c.id} href={`/cards/${c.id}`} className="flex items-center justify-between gap-4 rounded border border-border/60 px-3 py-2 hover:border-accent/60">
                  <span className="min-w-0 truncate">{c.player_name} · {c.side} {c.line ?? ""}</span>
                  <EdgeMeter edge={Number(c.edge)} bar={BAR} width={80} />
                </Link>
              ))}
            </div>
          </div>
        )}
      </section>

      {/* Games */}
      <section>
        <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-lg font-semibold">All {games.length} games · win probability</h2>
          <GameLegend />
        </div>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">{games.map((g) => <GameTile key={g.game_id} g={g} />)}</div>
      </section>

      {/* Props */}
      <section>
        <div className="mb-2 flex items-baseline justify-between">
          <h2 className="text-lg font-semibold">Player props · closest to the bar</h2>
          <Link href="/board" className="text-sm text-accent hover:underline">Full board →</Link>
        </div>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {props.sort((a, b) => Number(b.edge) - Number(a.edge)).slice(0, 9).map((c) => <PropTile key={c.id} c={c} bar={BAR} />)}
        </div>
      </section>
    </div>
  );
}
