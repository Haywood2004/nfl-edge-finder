import { sql } from "@/lib/db";

export const dynamic = "force-dynamic";

/** Paper-trade bet log.
 *  A bet is locked at the FIRST snapshot where a (week, market, player/team, side) pick clears
 *  edge ≥ PAPER_MIN_EDGE and confidence ≥ 55, at that snapshot's price. Graded after the game.
 *  Unit size = quarter-Kelly on a 100u bankroll, capped at 3u (the sheet can override).
 */
const PAPER_MIN_EDGE = 0.04;
const MIN_CONF = 55;

function kellyUnits(p: number, dec: number) {
  const b = dec - 1;
  const f = (p * b - (1 - p)) / b;
  return Math.max(0.25, Math.min(3, Math.round(f * 0.25 * 100 * 4) / 4));
}

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
    "model_prob", "market_prob", "edge", "confidence", "tier", "unit_size", "result", "actual", "clv", "kickoff_et", "card_id", "locked_at"];
  const esc = (v: unknown) => { const s = v == null ? "" : String(v); return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
  const mk: Record<string, string> = { player_pass_yds: "Pass Yds", h2h: "Moneyline" };
  const lines = rows.map((r) => {
    const dec = Number(r.price_decimal), p = Number(r.model_prob);
    const bet = r.market === "h2h" ? `${r.player_name} ML` : `${r.player_name} ${r.side} ${r.line}`;
    const kick = new Date(r.kickoff_utc);
    return [
      kick.toLocaleDateString("en-CA", { timeZone: "America/New_York" }), r.week, mk[r.market] ?? r.market, bet, r.team, r.opponent,
      r.side, r.line ?? "", dec.toFixed(3), r.price_american, r.book, p.toFixed(4), Number(r.market_prob).toFixed(4),
      Number(r.edge).toFixed(4), r.confidence, Number(r.edge) >= 0.15 ? "flagged" : "paper", kellyUnits(p, dec).toFixed(2),
      r.result ?? "", r.actual ?? "", r.clv_prob == null ? "" : Number(r.clv_prob).toFixed(4),
      kick.toLocaleString("en-US", { timeZone: "America/New_York", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }),
      r.id, new Date(r.created_at).toISOString(),
    ].map(esc).join(",");
  });
  return new Response([head.join(","), ...lines].join("\n") + "\n", {
    headers: { "content-type": "text/csv; charset=utf-8", "cache-control": "public, max-age=300" },
  });
}
