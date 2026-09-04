import { modelCards } from "@/lib/queries";
import { sql } from "@/lib/db";

export const dynamic = "force-dynamic";

/** Latest model run per market (metrics only) — used by the methodology page's consumers and for ops checks. */
export async function GET() {
  const rows = await modelCards();
  const [usage] = await sql`SELECT credits_remaining, ts FROM api_usage WHERE credits_remaining IS NOT NULL ORDER BY id DESC LIMIT 1`;
  return Response.json({ odds_api: usage ?? null, models: rows.map((r) => ({ id: r.id, market: r.market, version: r.version, trained_at: r.trained_at,
    train_seasons: r.train_seasons, test_seasons: r.test_seasons, metrics: r.metrics })) });
}
