import { modelCards } from "@/lib/queries";

export const dynamic = "force-dynamic";

/** Latest model run per market (metrics only) — used by the methodology page's consumers and for ops checks. */
export async function GET() {
  const rows = await modelCards();
  return Response.json(rows.map((r) => ({ id: r.id, market: r.market, version: r.version, trained_at: r.trained_at,
    train_seasons: r.train_seasons, test_seasons: r.test_seasons, metrics: r.metrics })));
}
