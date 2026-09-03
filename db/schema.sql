-- NFL Edge Finder — Postgres schema
-- Conventions:
--   raw_*   : source-shaped tables written only by ingest jobs. Nothing downstream reads them
--             except the feature builders in /pipeline/nfl_edge/features.
--   odds_*  : append-only odds snapshots (never overwritten, never deleted).
--   feat_*  : point-in-time features; every row carries as_of < kickoff.
--   model_* / projections / cards / grades : append-only model outputs and track record.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ---------------------------------------------------------------------------
-- RAW
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_games (
  game_id        text PRIMARY KEY,
  season         int NOT NULL,
  game_type      text,
  week           int NOT NULL,
  gameday        date,
  weekday        text,
  gametime       text,
  kickoff_utc    timestamptz,             -- derived from gameday+gametime (ET) at ingest
  away_team      text NOT NULL,
  home_team      text NOT NULL,
  location       text,                     -- Home | Neutral
  away_score     int,
  home_score     int,
  result         numeric,
  total          numeric,
  overtime       int,
  away_rest      int,
  home_rest      int,
  away_moneyline numeric,
  home_moneyline numeric,
  spread_line    numeric,
  total_line     numeric,
  div_game       int,
  roof           text,
  surface        text,
  temp           numeric,
  wind           numeric,
  away_qb_id     text,
  home_qb_id     text,
  away_qb_name   text,
  home_qb_name   text,
  stadium_id     text,
  stadium        text,
  ingested_at    timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE raw_games ADD COLUMN IF NOT EXISTS location text;
CREATE INDEX IF NOT EXISTS raw_games_season_week ON raw_games(season, week);

-- Curated column subset of nflverse pbp (full parquet kept in pipeline/.cache). See DECISIONS.md #4.
CREATE TABLE IF NOT EXISTS raw_pbp (
  play_id            numeric NOT NULL,
  game_id            text NOT NULL,
  season             int NOT NULL,
  week               int NOT NULL,
  season_type        text,
  posteam            text,
  defteam            text,
  home_team          text,
  away_team          text,
  qtr                int,
  down               int,
  ydstogo            int,
  yardline_100       int,
  game_seconds_remaining int,
  play_type          text,
  pass               int,
  rush               int,
  qb_dropback        int,
  qb_scramble        int,
  sack               int,
  complete_pass      int,
  incomplete_pass    int,
  interception       int,
  yards_gained       int,
  air_yards          numeric,
  yards_after_catch  numeric,
  passing_yards      numeric,
  rushing_yards      numeric,
  receiving_yards    numeric,
  epa                numeric,
  wpa                numeric,
  cpoe               numeric,
  success            numeric,
  xpass              numeric,
  pass_oe            numeric,
  touchdown          int,
  pass_touchdown     int,
  rush_touchdown     int,
  passer_player_id   text,
  passer_player_name text,
  receiver_player_id text,
  receiver_player_name text,
  rusher_player_id   text,
  rusher_player_name text,
  pass_location      text,
  pass_length        text,
  run_location       text,
  shotgun            int,
  no_huddle          int,
  score_differential int,
  PRIMARY KEY (game_id, play_id)
);
CREATE INDEX IF NOT EXISTS raw_pbp_season_week ON raw_pbp(season, week);
CREATE INDEX IF NOT EXISTS raw_pbp_defteam ON raw_pbp(defteam, season);

-- nflverse stats_player_week (subset of 150 columns; passing/rushing/receiving core)
CREATE TABLE IF NOT EXISTS raw_weekly_stats (
  player_id            text NOT NULL,
  player_name          text,
  position             text,
  season               int NOT NULL,
  week                 int NOT NULL,
  season_type          text,
  team                 text,
  opponent_team        text,
  completions          int,
  attempts             int,
  passing_yards        numeric,
  passing_tds          int,
  passing_interceptions int,
  sacks_suffered       numeric,
  passing_air_yards    numeric,
  passing_yards_after_catch numeric,
  passing_epa          numeric,
  passing_cpoe         numeric,
  carries              int,
  rushing_yards        numeric,
  rushing_tds          int,
  receptions           int,
  targets              int,
  receiving_yards      numeric,
  receiving_tds        int,
  receiving_air_yards  numeric,
  receiving_yards_after_catch numeric,
  target_share         numeric,
  air_yards_share      numeric,
  wopr                 numeric,
  fantasy_points_ppr   numeric,
  PRIMARY KEY (player_id, season, week, season_type)
);
CREATE INDEX IF NOT EXISTS raw_weekly_stats_sw ON raw_weekly_stats(season, week);

-- Injury reports; append-only history keyed by report date so upgrades/downgrades are visible.
CREATE TABLE IF NOT EXISTS raw_injuries (
  id                       bigserial PRIMARY KEY,
  season                   int NOT NULL,
  week                     int NOT NULL,
  season_type              text,
  team                     text,
  gsis_id                  text,
  full_name                text,
  position                 text,
  report_primary_injury    text,
  report_status            text,
  practice_primary_injury  text,
  practice_status          text,
  source                   text NOT NULL DEFAULT 'nflverse',
  observed_at              timestamptz NOT NULL DEFAULT now(),
  UNIQUE (season, week, season_type, team, gsis_id, report_status, practice_status, source)
);

CREATE TABLE IF NOT EXISTS raw_depth_charts (
  id           bigserial PRIMARY KEY,
  dt           timestamptz NOT NULL,
  season       int NOT NULL,
  team         text NOT NULL,
  player_name  text,
  gsis_id      text,
  pos_grp      text,
  pos_abb      text,
  pos_slot     int,
  pos_rank     int,
  UNIQUE (dt, team, gsis_id, pos_abb, pos_slot)
);
CREATE INDEX IF NOT EXISTS raw_depth_charts_team_dt ON raw_depth_charts(team, dt DESC);

CREATE TABLE IF NOT EXISTS raw_rosters (
  season       int NOT NULL,
  team         text NOT NULL,
  gsis_id      text NOT NULL,
  full_name    text,
  position     text,
  depth_chart_position text,
  status       text,
  years_exp    int,
  headshot_url text,
  PRIMARY KEY (season, gsis_id)
);

CREATE TABLE IF NOT EXISTS raw_snap_counts (
  game_id      text NOT NULL,
  season       int NOT NULL,
  week         int NOT NULL,
  pfr_player_id text NOT NULL,
  player       text,
  position     text,
  team         text,
  opponent     text,
  offense_snaps int,
  offense_pct  numeric,
  defense_snaps int,
  defense_pct  numeric,
  PRIMARY KEY (game_id, pfr_player_id)
);

CREATE TABLE IF NOT EXISTS raw_weather (
  id           bigserial PRIMARY KEY,
  game_id      text NOT NULL,
  fetched_at   timestamptz NOT NULL DEFAULT now(),
  source       text NOT NULL DEFAULT 'open-meteo',
  temp_f       numeric,
  wind_mph     numeric,
  precip_prob  numeric,
  precip_in    numeric,
  is_dome      boolean,
  raw          jsonb
);
CREATE INDEX IF NOT EXISTS raw_weather_game ON raw_weather(game_id, fetched_at DESC);

CREATE TABLE IF NOT EXISTS stadiums (
  team         text PRIMARY KEY,
  stadium      text,
  lat          numeric,
  lon          numeric,
  roof         text,        -- dome | outdoors | retractable
  tz           text
);

-- ---------------------------------------------------------------------------
-- ODDS (append-only)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS api_usage (
  id                 bigserial PRIMARY KEY,
  ts                 timestamptz NOT NULL DEFAULT now(),
  provider           text NOT NULL DEFAULT 'the-odds-api',
  endpoint           text NOT NULL,
  credits_used       int NOT NULL,
  credits_remaining  int,
  note               text
);

CREATE TABLE IF NOT EXISTS odds_snapshots (
  id            bigserial PRIMARY KEY,
  taken_at      timestamptz NOT NULL DEFAULT now(),
  label         text NOT NULL,      -- tue_open | thu | sat_night | sun_am | pre_kick | gameday_poll | manual
  season        int,
  week          int,
  markets       text[] NOT NULL,
  credits_used  int NOT NULL DEFAULT 0,
  source        text NOT NULL DEFAULT 'api'   -- api | file (recorded payload)
);

CREATE TABLE IF NOT EXISTS odds_events (
  event_id      text PRIMARY KEY,
  game_id       text REFERENCES raw_games(game_id),
  commence_time timestamptz NOT NULL,
  home_team     text NOT NULL,
  away_team     text NOT NULL,
  home_abbr     text,
  away_abbr     text,
  first_seen    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS odds_lines (
  id             bigserial PRIMARY KEY,
  snapshot_id    bigint NOT NULL REFERENCES odds_snapshots(id),
  event_id       text NOT NULL REFERENCES odds_events(event_id),
  market         text NOT NULL,       -- h2h | spreads | totals | player_pass_yds | ...
  bookmaker      text NOT NULL,
  book_title     text,
  player         text,                -- prop description (book's player name) or NULL
  player_id      text,                -- resolved nflverse gsis_id (may be NULL)
  side           text NOT NULL,       -- Over | Under | team name | Yes
  line           numeric,             -- point/handicap; NULL for h2h
  price_decimal  numeric NOT NULL,
  price_american int NOT NULL,
  book_last_update timestamptz
);
CREATE INDEX IF NOT EXISTS odds_lines_snap ON odds_lines(snapshot_id);
CREATE INDEX IF NOT EXISTS odds_lines_event_market ON odds_lines(event_id, market, player);

-- Per snapshot × event × market × player × line: consensus + best price + no-vig fair prob.
CREATE TABLE IF NOT EXISTS odds_consensus (
  id                 bigserial PRIMARY KEY,
  snapshot_id        bigint NOT NULL REFERENCES odds_snapshots(id),
  event_id           text NOT NULL,
  market             text NOT NULL,
  player             text,
  player_id          text,
  line               numeric,
  n_books            int NOT NULL,
  over_best_price    numeric,  over_best_book text,  over_best_american int,
  under_best_price   numeric,  under_best_book text, under_best_american int,
  over_consensus_prob  numeric,   -- mean no-vig prob across books
  under_consensus_prob numeric,
  UNIQUE (snapshot_id, event_id, market, player, line)
);

-- ---------------------------------------------------------------------------
-- FEATURES (point-in-time)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS feat_team_defense (
  season      int NOT NULL,
  week        int NOT NULL,          -- the week these features are FOR (built from data before it)
  team        text NOT NULL,
  as_of       timestamptz NOT NULL,
  games       int,
  pass_yds_allowed_pg   numeric,  pass_yds_allowed_rank int,
  pass_epa_allowed      numeric,  pass_epa_allowed_rank int,
  rush_yds_allowed_pg   numeric,  rush_yds_allowed_rank int,
  rush_epa_allowed      numeric,  rush_epa_allowed_rank int,
  dropbacks_faced_pg    numeric,
  yds_per_dropback_allowed numeric, yds_per_dropback_rank int,
  sack_rate             numeric,
  explosive_pass_rate_allowed numeric,
  yac_per_comp_allowed  numeric,
  wr_yds_allowed_pg     numeric,  wr_yds_allowed_rank int,
  te_yds_allowed_pg     numeric,  te_yds_allowed_rank int,
  rb_rec_yds_allowed_pg numeric,  rb_rec_yds_allowed_rank int,
  sos_adj_pass_yds_allowed numeric, sos_adj_pass_rank int,
  PRIMARY KEY (season, week, team)
);

CREATE TABLE IF NOT EXISTS feat_team_offense (
  season      int NOT NULL,
  week        int NOT NULL,
  team        text NOT NULL,
  as_of       timestamptz NOT NULL,
  games       int,
  plays_pg    numeric,
  pass_rate   numeric,
  proe        numeric,          -- pass rate over expectation
  sec_per_play numeric,
  epa_per_play numeric,
  pass_epa_per_db numeric,
  pass_yds_pg numeric,
  PRIMARY KEY (season, week, team)
);

-- One row per (player, game) for the market being modeled. Wide table; nullable where unavailable.
CREATE TABLE IF NOT EXISTS feat_player_game (
  season        int NOT NULL,
  week          int NOT NULL,
  game_id       text NOT NULL,
  player_id     text NOT NULL,
  player_name   text,
  position      text,
  team          text NOT NULL,
  opponent      text NOT NULL,
  is_home       boolean,
  kickoff_utc   timestamptz NOT NULL,
  as_of         timestamptz NOT NULL,
  features      jsonb NOT NULL,       -- flat {feature_name: value}
  target_passing_yards numeric,        -- NULL until game finalizes
  target_attempts      numeric,
  PRIMARY KEY (season, week, player_id, game_id)
);
CREATE INDEX IF NOT EXISTS feat_player_game_sw ON feat_player_game(season, week);

-- ---------------------------------------------------------------------------
-- MODELS / PROJECTIONS / CARDS / GRADES (append-only)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS model_runs (
  id           bigserial PRIMARY KEY,
  market       text NOT NULL,
  version      text NOT NULL,
  trained_at   timestamptz NOT NULL DEFAULT now(),
  train_seasons int[],
  valid_seasons int[],
  test_seasons  int[],
  metrics      jsonb NOT NULL,
  feature_names text[],
  artifact_path text,
  artifact      bytea             -- pickled model, so stateless runners (GitHub Actions) can load it
);
ALTER TABLE model_runs ADD COLUMN IF NOT EXISTS artifact bytea;

CREATE TABLE IF NOT EXISTS projections (
  id           bigserial PRIMARY KEY,
  model_run_id bigint NOT NULL REFERENCES model_runs(id),
  created_at   timestamptz NOT NULL DEFAULT now(),
  season       int NOT NULL,
  week         int NOT NULL,
  game_id      text NOT NULL,
  player_id    text NOT NULL,
  player_name  text,
  team         text,
  opponent     text,
  market       text NOT NULL,
  mean         numeric NOT NULL,
  sd           numeric NOT NULL,
  q10 numeric, q25 numeric, q50 numeric, q75 numeric, q90 numeric,
  factors      jsonb NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS projections_sw ON projections(season, week, market);

CREATE TABLE IF NOT EXISTS cards (
  id              bigserial PRIMARY KEY,
  created_at      timestamptz NOT NULL DEFAULT now(),
  season          int NOT NULL,
  week            int NOT NULL,
  game_id         text NOT NULL,
  event_id        text,
  player_id       text,
  player_name     text,
  position        text,
  team            text,
  opponent        text,
  kickoff_utc     timestamptz,
  market          text NOT NULL,
  side            text NOT NULL,
  line            numeric,
  price_american  int NOT NULL,
  price_decimal   numeric NOT NULL,
  book            text NOT NULL,
  snapshot_id     bigint REFERENCES odds_snapshots(id),
  projection_id   bigint REFERENCES projections(id),
  model_run_id    bigint REFERENCES model_runs(id),
  model_prob      numeric NOT NULL,
  market_prob     numeric NOT NULL,
  edge            numeric NOT NULL,
  ev_per_unit     numeric NOT NULL,
  confidence      int NOT NULL,
  score           numeric NOT NULL,     -- edge × confidence, feed default sort
  published       boolean NOT NULL DEFAULT false,
  factors         jsonb NOT NULL,
  line_open       numeric,
  line_open_snapshot_id bigint,
  book_prices     jsonb NOT NULL DEFAULT '[]',   -- [{book, side, line, american}] at publish
  trend_badges    text[] NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS cards_sw ON cards(season, week, published);

CREATE TABLE IF NOT EXISTS grades (
  id            bigserial PRIMARY KEY,
  card_id       bigint NOT NULL UNIQUE REFERENCES cards(id),
  graded_at     timestamptz NOT NULL DEFAULT now(),
  actual        numeric,
  result        text NOT NULL,       -- win | loss | push | void
  profit_units  numeric NOT NULL,
  closing_line  numeric,
  closing_price_american int,
  clv_prob      numeric              -- closing no-vig prob − published market_prob (positive = line moved toward us)
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
  id          bigserial PRIMARY KEY,
  job         text NOT NULL,
  started_at  timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz,
  status      text NOT NULL DEFAULT 'running',
  rows        int,
  detail      jsonb
);

-- Game-level win probabilities for the moneyline layer (append-only per scoring run)
CREATE TABLE IF NOT EXISTS game_projections (
  id                 bigserial PRIMARY KEY,
  model_run_id       bigint REFERENCES model_runs(id),
  created_at         timestamptz NOT NULL DEFAULT now(),
  season             int NOT NULL,
  week               int NOT NULL,
  game_id            text NOT NULL,
  snapshot_id        bigint REFERENCES odds_snapshots(id),
  home_team          text NOT NULL,
  away_team          text NOT NULL,
  kickoff_utc        timestamptz,
  p_home_model       numeric NOT NULL,     -- raw ratings model
  p_home_market      numeric,              -- sportsbook no-vig consensus
  p_home_polymarket  numeric,              -- Polymarket mid
  p_home_used        numeric NOT NULL,     -- blend used for cards
  elo_home           numeric, elo_away numeric,
  home_best          jsonb,                -- {book, american, decimal}
  away_best          jsonb,
  factors            jsonb NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS game_projections_sw ON game_projections(season, week);
