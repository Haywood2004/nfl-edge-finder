import { sql } from "@/lib/db";
import { kellyStake, exposureScale } from "@/lib/kelly";
import { barFor } from "@/lib/thresholds";

export const dynamic = "force-dynamic";

/** Log of bets actually placed. Writes need PLACED_BETS_TOKEN (Vercel env) — the password typed once into the screener's "log my bets" prompt. */
export async function GET(req: Request) {
  // ?check=1 with the password in the X-Placed-Token header → 204 if it matches (used by the unlock prompt)
  const url = new URL(req.url);
  if (url.searchParams.get("check")) {
    const token = process.env.PLACED_BETS_TOKEN;
    return new Response(null, { status: token && req.headers.get("x-placed-token") === token ? 204 : 401 });
  }
  if (url.searchParams.get("candidates")) {
    // picks you could log: one row per (week, market, player, side) — the last version published before kickoff, i.e.
    // the line the screener showed last — for the last 14 days. If you bet a different line, POST resolves the card
    // version at that line (a card is graded at its own line, so the logged card must carry the line you bet).
    const raw = await sql`
      SELECT DISTINCT ON (c.season, c.week, c.market, c.player_name, c.side)
             c.id AS card_id, c.season, c.week, c.player_name, c.team, c.opponent, c.market, c.side, c.line, c.book, c.price_american,
             c.price_decimal, c.model_prob, c.prob_calibrated, c.confidence, c.created_at,
             c.kickoff_utc, c.edge, c.edge_calibrated, g.result, g.actual
      FROM cards c LEFT JOIN grades g ON g.card_id = c.id
      WHERE c.source = 'model' AND c.market <> 'h2h' AND c.kickoff_utc > now() - interval '14 days' AND c.edge >= 0.04
        AND c.created_at < c.kickoff_utc
      ORDER BY c.season, c.week, c.market, c.player_name, c.side, c.created_at DESC`;
    // suggested stake = what the screener shows: ¼-Kelly on the calibrated prob, then the week's exposure scaling over
    // the bets that clear the bar (latest pre-kick version per pick) — lib/kelly.ts defaults
    const stakeRaw = (r: (typeof raw)[number]) => kellyStake(r.prob_calibrated != null ? Number(r.prob_calibrated) : Number(r.model_prob), Number(r.price_decimal));
    const clears = (r: (typeof raw)[number]) => Number(r.edge) >= barFor(r.market) && Number(r.confidence) >= 55;
    const scale: Record<string, number> = {};
    for (const wk of new Set(raw.map((r) => `${r.season}-${r.week}`))) {
      const latest = new Map<string, (typeof raw)[number]>();   // one version per pick, like the screener's card list
      for (const r of raw.filter((r) => `${r.season}-${r.week}` === wk && clears(r))) {
        const k = `${r.market}|${r.player_name}|${r.side}`;
        if (!latest.has(k) || new Date(r.created_at) > new Date(latest.get(k)!.created_at)) latest.set(k, r);
      }
      scale[wk] = exposureScale([...latest.values()].map(stakeRaw));
    }
    const rows = raw.map((r) => ({ ...r, suggested_stake: clears(r) ? Math.round(stakeRaw(r) * scale[`${r.season}-${r.week}`] * 20) / 20 : 0 }));
    return Response.json({ rows });
  }
  const rows = await sql`
    SELECT p.id, p.placed_at, p.stake_units, p.book, p.price_american, p.line, p.note, c.id AS card_id, c.player_name, c.market, c.side,
           c.team, c.opponent, c.kickoff_utc, c.season, c.week, c.edge, c.edge_calibrated, g.result, g.actual, g.profit_units, g.clv_prob
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
  // a bet at a different line than the card shown → log the card version that carries that line (grading is per card)
  let cid = Number(card_id);
  if (line != null) {
    const [c] = await sql`SELECT season, week, market, player_name, side, line FROM cards WHERE id = ${cid}`;
    if (c && Number(c.line) !== Number(line)) {
      const [alt] = await sql`
        SELECT id FROM cards WHERE source = 'model' AND season = ${c.season} AND week = ${c.week} AND market = ${c.market}
          AND player_name = ${c.player_name} AND side = ${c.side} AND line = ${Number(line)} AND created_at < kickoff_utc
        ORDER BY created_at DESC LIMIT 1`;
      if (!alt) {
        const lines = await sql`SELECT DISTINCT line FROM cards WHERE source = 'model' AND season = ${c.season} AND week = ${c.week}
          AND market = ${c.market} AND player_name = ${c.player_name} AND side = ${c.side} AND created_at < kickoff_utc ORDER BY line`;
        return new Response(`The model never priced ${c.player_name} ${c.side} ${line}. Lines it did price: ${lines.map((l) => Number(l.line)).join(", ")}`, { status: 422 });
      }
      cid = Number(alt.id);
    }
  }
  await sql`DELETE FROM placed_bets WHERE card_id = ${cid}`;
  const [row] = await sql`
    INSERT INTO placed_bets (card_id, stake_units, book, price_american, line, note)
    VALUES (${cid}, ${Number(stake_units) || 1}, ${book ?? null}, ${price_american == null ? null : Number(price_american)}, ${line == null ? null : Number(line)}, ${note ?? null})
    RETURNING id`;
  return Response.json({ ok: true, id: row.id });
}
