import { sql } from "@/lib/db";

export const dynamic = "force-dynamic";

/** Closing-line backtest bets (from `backtest_bets`, written by the pipeline's export_backtest job) in a compact
 *  column-array form so the Backtest lab can re-run any edge / Kelly / exposure setting in the browser. */
export async function GET() {
  const rows = await sql`
    SELECT season, week, market, player_name, team, opponent, book, line, side, price_decimal, market_prob, model_prob,
           prob_calibrated, edge, actual, result
    FROM backtest_bets ORDER BY season, week, market, player_name`;
  const cols = ["season", "week", "market", "player", "team", "opp", "book", "line", "side", "dec", "fair", "p", "p_cal", "edge", "actual", "result"] as const;
  const data = rows.map((r) => [
    r.season, r.week, r.market, r.player_name, r.team, r.opponent, r.book, Number(r.line), r.side, Number(r.price_decimal),
    Number(r.market_prob), Number(r.model_prob), r.prob_calibrated == null ? null : Number(r.prob_calibrated), Number(r.edge),
    r.actual == null ? null : Number(r.actual), r.result,
  ]);
  return Response.json({ cols, rows: data, generated_at: new Date().toISOString() }, {
    headers: { "cache-control": "public, max-age=3600, s-maxage=3600" },
  });
}
