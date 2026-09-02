import { latestCards } from "@/lib/queries";
import { Feed } from "@/components/Feed";
import { Freshness } from "@/components/Freshness";

export const dynamic = "force-dynamic";

export default async function Home() {
  const cards = await latestCards();
  const week = cards[0];
  const published = cards.filter((c) => c.published);
  return (
    <div>
      <div className="mb-4 flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-xl font-semibold">This Week{week ? ` · ${week.season} Week ${week.week}` : ""}</h1>
          <p className="text-sm text-muted">
            {published.length} model pick{published.length === 1 ? "" : "s"} clear the bar (edge ≥ 4%, confidence ≥ 55).
            {published.length < cards.length && ` ${cards.length - published.length} more sit below it on the full board.`}
          </p>
        </div>
        <Freshness />
      </div>
      <Feed cards={cards} showAll={false} />
    </div>
  );
}
