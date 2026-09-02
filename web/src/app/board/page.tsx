import { latestCards } from "@/lib/queries";
import { Feed } from "@/components/Feed";
import { Freshness } from "@/components/Freshness";

export const dynamic = "force-dynamic";

export default async function Board() {
  const cards = await latestCards();
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
    </div>
  );
}
