import { sql } from "@/lib/db";

export const dynamic = "force-dynamic";

/** Log of bets actually placed. Writes need PLACED_BETS_TOKEN (Vercel env) — the password typed once into the screener's "log my bets" prompt. */
export async function GET(req: Request) {
  // ?check=1 with the password in the X-Placed-Token header → 204 if it matches (used by the unlock prompt)
  const url = new URL(req.url);
  if (url.searchParams.get("check")) {
    const token = process.env.PLACED_BETS_TOKEN;
    return new Response(null, { status: token && req.headers.get("x-placed-token") === token ? 204 : 401 });
  }
  const rows = await sql`
    SELECT p.id, p.placed_at, p.stake_units, p.book, p.price_american, p.line, p.note, c.id AS card_id, c.player_name, c.market, c.side,
           c.team, c.opponent, c.kickoff_utc, c.edge, c.edge_calibrated, g.result, g.actual, g.profit_units, g.clv_prob
    FROM placed_bets p JOIN cards c ON c.id = p.card_id LEFT JOIN grades g ON g.card_id = c.id
    ORDER BY c.kickoff_utc DESC, p.placed_at DESC`;
  return Response.json({ rows });
}

export async function POST(req: Request) {
  const body = await req.json().catch(() => null);
  const token = process.env.PLACED_BETS_TOKEN;
  if (!token || body?.token !== token) return new Response("unauthorized", { status: 401 });
  const { card_id, stake_units, book, price_american, line, note, remove } = body;
  if (!card_id) return new Response("card_id required", { status: 400 });
  if (remove) {
    await sql`DELETE FROM placed_bets WHERE card_id = ${Number(card_id)}`;
    return Response.json({ ok: true, removed: true });
  }
  const [row] = await sql`
    INSERT INTO placed_bets (card_id, stake_units, book, price_american, line, note)
    VALUES (${Number(card_id)}, ${Number(stake_units)}, ${book ?? null}, ${price_american == null ? null : Number(price_american)}, ${line == null ? null : Number(line)}, ${note ?? null})
    RETURNING id`;
  return Response.json({ ok: true, id: row.id });
}
