import { latestCards, latestGameProjections } from "@/lib/queries";
import { KellyTable } from "@/components/KellyTable";

export const dynamic = "force-dynamic";
export const metadata = { title: "Kelly sizing" };

export default async function KellyPage() {
  const [cards, games] = await Promise.all([latestCards(), latestGameProjections()]);
  const wk = cards[0] ?? games[0];
  return (
    <div className="space-y-6">
      <div>
        <p className="eyebrow">{wk ? `${wk.season} · Week ${wk.week}` : "This week"}</p>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight">Kelly sizing</h1>
        <p className="mt-1 max-w-2xl text-sm text-muted">
          How much of the bankroll each priced bet deserves. Full Kelly <span className="mono">f* = (p·b − q) / b</span> maximises long-run growth
          if the model&apos;s probability is exactly right — it never is, so the default is quarter-Kelly, capped at 3% per leg. The paper-bet feed and the Google Sheet use exactly these numbers.
        </p>
      </div>
      <KellyTable cards={cards} />
    </div>
  );
}
