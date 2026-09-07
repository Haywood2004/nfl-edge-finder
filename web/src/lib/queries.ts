import { sql } from "./db";

export type Factor = {
  factor: string; value: unknown; impact: "+" | "−" | "▬"; impact_over: number; magnitude: number; text: string;
  source?: { table: string; key?: string; team?: string };
};
export type Card = {
  id: number; created_at: string; season: number; week: number; game_id: string; event_id: string | null; player_id: string;
  player_name: string; position: string; team: string; opponent: string; kickoff_utc: string; market: string;
  side: string; line: number; price_american: number; price_decimal: number; book: string; snapshot_id: number;
  projection_id: number; model_run_id: number; model_prob: number; market_prob: number; edge: number;
  ev_per_unit: number; confidence: number; score: number; published: boolean; source?: string; factors: Factor[];
  line_open: number | null; book_prices: { book: string; line: number; over: number; under: number }[];
  trend_badges: string[]; home_team: string; away_team: string;
  /** "blend" (default, what the pipeline publishes) or "raw" (synthetic card from the un-anchored ratings model) */
  basis?: "blend" | "raw"; href?: string;
  /** learned shrinkage (models/calibration.py): null until the calibrator has been trained */
  prob_calibrated: number | null; edge_calibrated: number | null;
};

/** Cards from the most recent scoring run for the current target week. */
export async function latestCards(opts: { publishedOnly?: boolean } = {}) {
  const rows = await sql<Card[]>`
    WITH tw AS (SELECT season, week FROM cards WHERE source = 'model' ORDER BY kickoff_utc DESC, created_at DESC LIMIT 1),
         run AS (SELECT market, max(created_at) AS ts FROM cards c JOIN tw USING (season, week) WHERE c.source = 'model' GROUP BY market)
    SELECT c.*, g.home_team, g.away_team
    FROM cards c JOIN tw USING (season, week) JOIN run ON c.created_at = run.ts AND c.market = run.market
    JOIN raw_games g USING (game_id)
    WHERE c.source = 'model' ${opts.publishedOnly ? sql`AND c.published` : sql``}
    ORDER BY c.score DESC, c.edge DESC`;
  return rows;
}

export async function cardById(id: number) {
  const rows = await sql<Card[]>`SELECT c.*, g.home_team, g.away_team FROM cards c JOIN raw_games g USING (game_id) WHERE c.id = ${id}`;
  return rows[0] ?? null;
}

export async function projection(id: number) {
  const rows = await sql`SELECT * FROM projections WHERE id = ${id}`;
  return rows[0] ?? null;
}

export async function lineHistory(eventId: string, market: string, player: string) {
  return sql`
    SELECT s.id AS snapshot_id, s.taken_at, s.label, l.bookmaker, l.side, l.line, l.price_american
    FROM odds_lines l JOIN odds_snapshots s ON s.id = l.snapshot_id
    WHERE l.event_id = ${eventId} AND l.market = ${market} AND l.player = ${player}
    ORDER BY s.taken_at, l.bookmaker, l.side`;
}

/** Stat column + usage column per market, for game logs. */
export const MARKET_STAT: Record<string, { stat: string; usage: string; usageLabel: string; statLabel: string }> = {
  player_pass_yds: { stat: "passing_yards", usage: "attempts", usageLabel: "Att", statLabel: "Yds" },
  player_reception_yds: { stat: "receiving_yards", usage: "targets", usageLabel: "Tgt", statLabel: "Yds" },
  player_receptions: { stat: "receptions", usage: "targets", usageLabel: "Tgt", statLabel: "Rec" },
  player_rush_yds: { stat: "rushing_yards", usage: "carries", usageLabel: "Car", statLabel: "Yds" },
};

export async function playerGameLog(playerId: string, market = "player_pass_yds", n = 10) {
  const m = MARKET_STAT[market] ?? MARKET_STAT.player_pass_yds;
  return sql<{ season: number; week: number; team: string; opponent: string; usage: number; stat: number }[]>`
    SELECT season, week, team, opponent_team AS opponent, ${sql(m.usage)} AS usage, ${sql(m.stat)} AS stat
    FROM raw_weekly_stats WHERE player_id = ${playerId} AND season_type = 'REG' AND ${sql(m.usage)} >= ${market === "player_pass_yds" ? 10 : 1}
    ORDER BY season DESC, week DESC LIMIT ${n}`;
}

/** What the opponent allowed to this position (top player per game) in its last n games. */
export async function opponentLastGames(team: string, market = "player_pass_yds", position = "QB", n = 10) {
  const m = MARKET_STAT[market] ?? MARKET_STAT.player_pass_yds;
  const pos = market === "player_pass_yds" ? ["QB"] : market === "player_rush_yds" ? ["RB", "FB"] : [position === "TE" ? "TE" : position === "RB" || position === "FB" ? "RB" : "WR"];
  return sql<{ season: number; week: number; offense: string; player_name: string; stat: number }[]>`
    SELECT DISTINCT ON (w.season, w.week) w.season, w.week, w.team AS offense, w.player_name, ${sql(m.stat)} AS stat
    FROM raw_weekly_stats w
    WHERE w.opponent_team = ${team} AND w.position = ANY(${pos}) AND w.season_type = 'REG' AND ${sql(m.stat)} IS NOT NULL
    ORDER BY w.season DESC, w.week DESC, ${sql(m.stat)} DESC LIMIT ${n}`;
}

export async function defenseTable(season: number, week: number) {
  return sql`SELECT * FROM feat_team_defense WHERE season = ${season} AND week = ${week} ORDER BY pass_yds_allowed_rank`;
}

export async function teamInjuries(season: number, week: number, teams: string[]) {
  return sql`
    SELECT DISTINCT ON (gsis_id) team, full_name, position, report_status, practice_status, report_primary_injury, observed_at
    FROM raw_injuries WHERE season = ${season} AND week = ${week} AND team = ANY(${teams})
    ORDER BY gsis_id, observed_at DESC`;
}

export async function freshness() {
  const [r] = await sql`
    SELECT (SELECT max(taken_at) FROM odds_snapshots WHERE label NOT LIKE 'live_%') AS odds_at,
           (SELECT max(created_at) FROM cards WHERE source = 'model') AS scored_at,
           (SELECT max(trained_at) FROM model_runs) AS trained_at,
           (SELECT max(observed_at) FROM raw_injuries) AS injuries_at,
           (SELECT max(finished_at) FROM pipeline_runs WHERE job LIKE 'ingest_%' AND status='ok') AS ingested_at`;
  return r as { odds_at: string; scored_at: string; trained_at: string; injuries_at: string; ingested_at: string };
}

export async function trackRecord() {
  const [r] = await sql`
    SELECT count(*)::int AS n, sum((result='win')::int)::int AS wins, sum((result='loss')::int)::int AS losses,
           sum((result='push')::int)::int AS pushes, coalesce(sum(profit_units),0)::float AS units,
           avg(clv_prob)::float AS clv
    FROM grades g JOIN cards c ON c.id = g.card_id WHERE c.published AND c.source = 'model'`;
  return r as { n: number; wins: number; losses: number; pushes: number; units: number; clv: number | null };
}

export type GameProjection = {
  id: number; created_at: string; season: number; week: number; game_id: string; home_team: string; away_team: string;
  kickoff_utc: string; p_home_model: number; p_home_market: number | null; p_home_polymarket: number | null;
  p_home_used: number; elo_home: number; elo_away: number;
  home_best: { book: string; american: number; dec: number } | null; away_best: { book: string; american: number; dec: number } | null;
  factors: Factor[];
};

export async function latestGameProjections() {
  return sql<GameProjection[]>`
    WITH tw AS (SELECT season, week FROM game_projections ORDER BY kickoff_utc DESC, created_at DESC LIMIT 1),
         run AS (SELECT max(created_at) AS ts FROM game_projections g JOIN tw USING (season, week))
    SELECT g.* FROM game_projections g JOIN tw USING (season, week) JOIN run ON g.created_at = run.ts
    ORDER BY g.kickoff_utc, g.game_id`;
}

export async function gameCards(gameId: string) {
  return sql<Card[]>`
    WITH run AS (SELECT max(created_at) AS ts FROM cards WHERE game_id = ${gameId} AND market = 'h2h' AND source = 'model')
    SELECT c.*, g.home_team, g.away_team FROM cards c JOIN raw_games g USING (game_id) JOIN run ON c.created_at = run.ts
    WHERE c.game_id = ${gameId} AND c.market = 'h2h' ORDER BY c.edge DESC`;
}

export type ModelCard = {
  id: number; market: string; version: string; trained_at: string; train_seasons: number[]; test_seasons: number[];
  metrics: Record<string, unknown>; feature_names: string[];
};
/** Latest model run per market, for the methodology page's model card. */
export async function modelCards() {
  return sql<ModelCard[]>`
    SELECT DISTINCT ON (market) id, market, version, trained_at, train_seasons, test_seasons, metrics, feature_names
    FROM model_runs ORDER BY market, id DESC`;
}

/** Track record broken down by market, tier and week. */
export async function trackBreakdown() {
  return sql<{ kind: string; key: string; n: number; wins: number; losses: number; pushes: number; units: number; clv: number | null }[]>`
    WITH g AS (
      SELECT c.market, c.week, CASE WHEN c.edge >= (CASE WHEN c.market='h2h' THEN 0.15 WHEN c.market='player_pass_yds' THEN 0.08 WHEN c.market='player_reception_yds' THEN 0.10 WHEN c.market='player_receptions' THEN 0.15 ELSE 0.06 END) THEN 'flagged' ELSE 'paper' END AS tier, gr.result, gr.profit_units, gr.clv_prob
      FROM grades gr JOIN cards c ON c.id = gr.card_id WHERE c.source = 'model')
    SELECT 'market' AS kind, market AS key, count(*)::int n, sum((result='win')::int)::int wins, sum((result='loss')::int)::int losses,
           sum((result='push')::int)::int pushes, coalesce(sum(profit_units),0)::float units, avg(clv_prob)::float clv FROM g GROUP BY market
    UNION ALL
    SELECT 'tier', tier, count(*)::int, sum((result='win')::int)::int, sum((result='loss')::int)::int, sum((result='push')::int)::int, coalesce(sum(profit_units),0)::float, avg(clv_prob)::float FROM g GROUP BY tier
    UNION ALL
    SELECT 'week', week::text, count(*)::int, sum((result='win')::int)::int, sum((result='loss')::int)::int, sum((result='push')::int)::int, coalesce(sum(profit_units),0)::float, avg(clv_prob)::float FROM g GROUP BY week
    ORDER BY 1, 2`;
}


/** Synthetic moneyline cards from the UN-ANCHORED ratings model, one per side per game where that side's
 *  raw probability beats the fair probability at the best available price. These are NOT published picks:
 *  the raw model loses vs closing lines in every backtest bucket (MODEL.md), so the pipeline blends it 95%
 *  toward the market before it makes cards. The Full Board exposes them behind a basis toggle so the model's
 *  own opinion is visible and trackable, labelled as such. */
export function rawMoneylineCards(games: GameProjection[]): Card[] {
  const out: Card[] = [];
  for (const g of games) {
    const pm = Number(g.p_home_model);
    const pb = g.p_home_market == null ? null : Number(g.p_home_market);
    const factors = (g.factors ?? []).map((f) => ({ ...f, impact: (f as { impact?: "+" | "−" | "▬" }).impact ?? "▬" }));
    for (const [side, p, best, opp] of [[g.home_team, pm, g.home_best, g.away_team], [g.away_team, 1 - pm, g.away_best, g.home_team]] as const) {
      if (!best) continue;
      const fair = pb == null ? 1 / best.dec : side === g.home_team ? pb : 1 - pb;
      const edge = p - fair;
      if (edge < 0.02) continue;
      const ev = p * (best.dec - 1) - (1 - p);
      const explain = {
        factor: "raw_basis", value: edge, impact: "▬" as const, impact_over: 0, magnitude: 1,
        text: `Un-anchored ratings model: ${TEAM_LABEL(side)} ${(p * 100).toFixed(1)}% vs market ${(fair * 100).toFixed(1)}%. ` +
          "This basis is NOT a published pick: bet against closing lines 2019–2025 the raw model lost at every edge threshold (≥15%: −13.9% ROI).",
        source: { table: "model_runs", key: "metrics" },
      };
      out.push({
        id: -Math.abs(hash(`${g.game_id}:${side}`)), created_at: g.created_at, season: g.season, week: g.week, game_id: g.game_id,
        event_id: null, player_id: side, player_name: TEAM_LABEL(side), position: "TEAM", team: side, opponent: opp,
        kickoff_utc: g.kickoff_utc, market: "h2h", side, line: 0, price_american: best.american, price_decimal: best.dec,
        book: best.book, snapshot_id: 0, projection_id: 0, model_run_id: 0, model_prob: p, market_prob: fair, edge,
        ev_per_unit: ev, confidence: 30, score: edge * 30, published: false,
        factors: [explain, ...factors], line_open: null, book_prices: [], trend_badges: [],
        home_team: g.home_team, away_team: g.away_team, basis: "raw", href: `/games/${g.game_id}`, prob_calibrated: null, edge_calibrated: null,
      });
    }
  }
  return out.sort((a, b) => Number(b.edge) - Number(a.edge));
}

const TEAM_LABEL = (abbr: string) => abbr;
function hash(s: string) { let h = 0; for (const ch of s) h = (h * 31 + ch.charCodeAt(0)) | 0; return h || 1; }
