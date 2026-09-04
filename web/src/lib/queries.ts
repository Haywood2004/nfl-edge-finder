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
  ev_per_unit: number; confidence: number; score: number; published: boolean; factors: Factor[];
  line_open: number | null; book_prices: { book: string; line: number; over: number; under: number }[];
  trend_badges: string[]; home_team: string; away_team: string;
};

/** Cards from the most recent scoring run for the current target week. */
export async function latestCards(opts: { publishedOnly?: boolean } = {}) {
  const rows = await sql<Card[]>`
    WITH tw AS (SELECT season, week FROM cards ORDER BY kickoff_utc DESC, created_at DESC LIMIT 1),
         run AS (SELECT market, max(created_at) AS ts FROM cards c JOIN tw USING (season, week) GROUP BY market)
    SELECT c.*, g.home_team, g.away_team
    FROM cards c JOIN tw USING (season, week) JOIN run ON c.created_at = run.ts AND c.market = run.market
    JOIN raw_games g USING (game_id)
    ${opts.publishedOnly ? sql`WHERE c.published` : sql``}
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

export async function playerGameLog(playerId: string, n = 10) {
  return sql`
    SELECT season, week, team, opponent_team AS opponent, attempts, completions, passing_yards, passing_tds
    FROM raw_weekly_stats WHERE player_id = ${playerId} AND season_type = 'REG' AND attempts >= 10
    ORDER BY season DESC, week DESC LIMIT ${n}`;
}

export async function opponentLastGames(team: string, n = 10) {
  return sql`
    SELECT w.season, w.week, w.team AS offense, w.player_name, w.passing_yards
    FROM raw_weekly_stats w
    WHERE w.opponent_team = ${team} AND w.position = 'QB' AND w.season_type = 'REG' AND w.attempts >= 10
    ORDER BY w.season DESC, w.week DESC LIMIT ${n}`;
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
    SELECT (SELECT max(taken_at) FROM odds_snapshots) AS odds_at,
           (SELECT max(created_at) FROM cards) AS scored_at,
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
    FROM grades g JOIN cards c ON c.id = g.card_id WHERE c.published`;
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
    WITH run AS (SELECT max(created_at) AS ts FROM cards WHERE game_id = ${gameId} AND market = 'h2h')
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
      SELECT c.market, c.week, CASE WHEN c.edge >= 0.15 THEN 'flagged' ELSE 'paper' END AS tier, gr.result, gr.profit_units, gr.clv_prob
      FROM grades gr JOIN cards c ON c.id = gr.card_id)
    SELECT 'market' AS kind, market AS key, count(*)::int n, sum((result='win')::int)::int wins, sum((result='loss')::int)::int losses,
           sum((result='push')::int)::int pushes, coalesce(sum(profit_units),0)::float units, avg(clv_prob)::float clv FROM g GROUP BY market
    UNION ALL
    SELECT 'tier', tier, count(*)::int, sum((result='win')::int)::int, sum((result='loss')::int)::int, sum((result='push')::int)::int, coalesce(sum(profit_units),0)::float, avg(clv_prob)::float FROM g GROUP BY tier
    UNION ALL
    SELECT 'week', week::text, count(*)::int, sum((result='win')::int)::int, sum((result='loss')::int)::int, sum((result='push')::int)::int, coalesce(sum(profit_units),0)::float, avg(clv_prob)::float FROM g GROUP BY week
    ORDER BY 1, 2`;
}
