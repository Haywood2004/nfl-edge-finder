import { latestCards, latestGameProjections } from "@/lib/queries";
import { GameTile, GameLegend } from "@/components/GameTile";
import { Feed } from "@/components/Feed";
import { Freshness } from "@/components/Freshness";

export const dynamic = "force-dynamic";

export default async function Board() {
  const [cards, games] = await Promise.all([latestCards(), latestGameProjections()]);
  return (
    <div>
      <div className="mb-4 flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-xl font-semibold">Full Board</h1>
          <p className="text-sm text-muted">Every player-side the model priced this week, including those below the publish threshold.</p>
        </div>
        <Freshness />
      </div>
      <Feed cards={cards} showAll />
      <section className="mt-8">
        <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-lg font-semibold">All games · moneyline</h2>
          <GameLegend />
        </div>
        <p className="mb-3 text-sm text-muted">Every game is priced. A moneyline card appears above only when a venue pays more than the blended probability implies — games with no card are priced in line with the consensus everywhere.</p>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">{games.map((g) => <GameTile key={g.game_id} g={g} />)}</div>
      </section>
    </div>
  );
}
