import { sql } from "@/lib/db";
import { kellyFull, kellyStake, DEFAULT_BANKROLL, DEFAULT_FRACTION } from "@/lib/kelly";
import { barFor } from "@/lib/thresholds";

export const dynamic = "force-dynamic";

/** Paper-trade bet log.
 *  A bet is locked at the FIRST snapshot where a (week, market, player/team, side) pick clears
 *  edge ≥ PAPER_MIN_EDGE and confidence ≥ 55, at that snapshot's price. Graded after the game.
 *  Unit size = quarter-Kelly on a 100u bankroll, capped at 3% (lib/kelly.ts — same numbers as the /kelly page).
 */
const PAPER_MIN_EDGE = 0.04;
const MIN_CONF = 55;

export async function GET() {
  const rows = await sql`
    WITH q AS (
      SELECT DISTINCT ON (c.season, c.week, c.market, c.player_name, c.side)
             c.*, g.result, g.actual, g.profit_units, g.clv_prob
      FROM cards c LEFT JOIN grades g ON g.card_id = c.id
      WHERE c.edge >= ${PAPER_MIN_EDGE} AND c.confidence >= ${MIN_CONF} AND c.created_at < c.kickoff_utc
      ORDER BY c.season, c.week, c.market, c.player_name, c.side, c.created_at ASC)
    SELECT * FROM q ORDER BY kickoff_utc, market, player_name`;
  const head = ["date", "week", "market", "bet", "team", "opponent", "side", "line", "odds_decimal", "odds_american", "book",
    "model_prob", "market_prob", "edge", "confidence", "tier", "unit_size", "result", "actual", "clv", "kickoff_et", "card_id", "locked_at",
    "kelly_full_pct", "kelly_fraction", "bankroll_units", "edge_calibrated", "prob_calibrated"];
  const esc = (v: unknown) => { const s = v == null ? "" : String(v); return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
  const mk: Record<string, string> = { player_pass_yds: "Pass Yds", player_reception_yds: "Rec Yds", player_rush_yds: "Rush Yds", player_receptions: "Receptions", h2h: "Moneyline" };
  const lines = rows.map((r) => {
    const dec = Number(r.price_decimal), p = r.prob_calibrated != null ? Number(r.prob_calibrated) : Number(r.model_prob);
    const bet = r.market === "h2h" ? `${r.player_name} ML` : `${r.player_name} ${r.side} ${r.line}`;
    const kick = new Date(r.kickoff_utc);
    return [
      kick.toLocaleDateString("en-CA", { timeZone: "America/New_York" }), r.week, mk[r.market] ?? r.market, bet, r.team, r.opponent,
      r.side, r.line ?? "", dec.toFixed(3), r.price_american, r.book, p.toFixed(4), Number(r.market_prob).toFixed(4),
      Number(r.edge).toFixed(4), r.confidence, Number(r.edge) >= barFor(r.market) ? "flagged" : "paper", Math.max(kellyStake(p, dec), 0.1).toFixed(2),
      r.result ?? "", r.actual ?? "", r.clv_prob == null ? "" : Number(r.clv_prob).toFixed(4),
      kick.toLocaleString("en-US", { timeZone: "America/New_York", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }),
      r.id, new Date(r.created_at).toISOString(),
      (kellyFull(p, dec) * 100).toFixed(2), DEFAULT_FRACTION, DEFAULT_BANKROLL,
      r.edge_calibrated == null ? "" : Number(r.edge_calibrated).toFixed(4), r.prob_calibrated == null ? "" : Number(r.prob_calibrated).toFixed(4),
    ].map(esc).join(",");
  });
  return new Response([head.join(","), ...lines].join("\n") + "\n", {
    headers: { "content-type": "text/csv; charset=utf-8", "cache-control": "public, max-age=300" },
  });
}
