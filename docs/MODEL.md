# MODEL.md — passing yards (py-lgbm-v2)

Last retrain: 2026-09-04 21:20 UTC · model_run id 40

## Protocol

Walk-forward: train 2016–2022 → validate 2023 (early stopping, scale calibration) → test 2024–2025. Production artifact refit on all seasons with the validated iteration count. Target = passing yards in games with ≥10 attempts, modelled RELATIVE to the previous season's league-average starter passing yards (v2; removes the era-drift bias that over-projected 2024–25 by 6–9 yds). Distribution = mean + heteroscedastic sd × empirical standardised-residual distribution (v2; replaces the Normal). Mean model iterations 306, scale calibration k=1.050.

v2 feature additions: coaching-regime flag (new head coach → league-average tendency priors), script-neutral pass rate / pace / shotgun / no-huddle rates, injury context (own skill & OL outs, share of prior targets ruled out, WR1 out; opponent DB and front-seven outs) from 2016–2025 official reports + live ESPN feed, and league passing environment (rolling 8-week and prior-season means).

## Holdout (2024–2025)

| metric | value |
|---|---|
| games | 1129 |
| MAE (model) | 57.79 |
| RMSE | 72.58 |
| MAE baseline: EWM of player's yards | 60.28 |
| MAE baseline: previous-season avg | 64.52 |
| MAE proxy market (player-only LGBM) | 59.18 |
| q10 / q25 / q75 / q90 coverage | 0.113 / 0.267 / 0.745 / 0.895 (ideal .10/.25/.75/.90) |

### P(over) calibration at synthetic lines (holdout)

| predicted bucket | n | mean predicted | actual over rate |
|---|---|---|---|
| (0.2, 0.3] | 1034 | 0.278 | 0.285 |
| (0.3, 0.4] | 1080 | 0.380 | 0.377 |
| (0.4, 0.5] | 2402 | 0.467 | 0.457 |
| (0.5, 0.6] | 1424 | 0.558 | 0.540 |
| (0.6, 0.7] | 1190 | 0.633 | 0.630 |
| (0.7, 0.8] | 773 | 0.715 | 0.708 |

### Simulated betting vs PROXY market (holdout) — NOT real closing lines

Lines = proxy model median (player-only features, no opponent/context) ± 0.5; price −110 both sides. This measures whether matchup/context features add information over a 'the book knows the average' line. Real closing-line ROI accrues in the track record from live snapshots only.

| min edge | bets | wins | win rate | ROI |
|---|---|---|---|---|
| =0.02 | 902 | 524 | 0.581 | +0.109 |
| =0.04 | 687 | 407 | 0.592 | +0.131 |
| =0.06 | 516 | 315 | 0.610 | +0.165 |
| =0.08 | 332 | 204 | 0.614 | +0.173 |

## Validation (2023)

MAE 59.47 · coverage q25 0.245 / q75 0.717

## Top features (gain share)

| feature | share |
|---|---|
| py_ewm | 0.193 |
| implied_total | 0.097 |
| epa_att_ewm | 0.071 |
| league_py_prev_season | 0.047 |
| total_line | 0.043 |
| py_l10 | 0.036 |
| py_l5 | 0.028 |
| py_std_avg | 0.028 |
| days_since_last | 0.026 |
| wind | 0.024 |
| py_prev_season | 0.020 |
| week_num | 0.017 |
| team_games | 0.016 |
| team_neutral_pass_rate | 0.014 |
| opp_sos_adj_pass_yds_allowed | 0.014 |
| py_sd_l10 | 0.014 |
| opp_rush_yds_allowed_pg | 0.012 |
| sack_rate_ewm | 0.012 |
| team_pass_yds_pg | 0.012 |
| team_plays_pg | 0.011 |
| att_l5 | 0.011 |
| temp | 0.010 |
| opp_pass_epa_allowed | 0.010 |
| league_att_l8 | 0.010 |
| opp_pass_yds_allowed_pg | 0.010 |

All 74 features: dome, temp, wind, py_l3, py_l5, att_l3, att_l5, new_hc, ol_out, py_ewm, py_l10, att_ewm, is_home, wr1_out, ypa_ewm, ypa_l10, cpoe_ewm, div_game, new_team, week_num, games_std, opp_games, primetime, py_sd_l10, rest_days, skill_out, team_proe, opp_db_out, py_std_avg, team_games, total_line, air_yds_ewm, epa_att_ewm, spread_team, usage_trend, coach_tenure, games_career, league_py_l8, rush_yds_ewm, implied_total, league_att_l8, opp_front_out, opp_sack_rate, sack_rate_ewm, team_plays_pg, py_prev_season, team_pass_rate, days_since_last, target_share_out, team_pass_yds_pg, games_prev_season, team_epa_per_play, team_shotgun_rate, injury_report_seen, team_no_huddle_rate, opp_pass_epa_allowed, opp_rush_epa_allowed, team_pass_epa_per_db, league_py_prev_season, opp_sos_adj_pass_rank, opp_te_yds_allowed_pg, opp_wr_yds_allowed_pg, team_neutral_plays_pg, opp_dropbacks_faced_pg, team_neutral_pass_rate, opp_pass_yds_allowed_pg, opp_rush_yds_allowed_pg, opp_yac_per_comp_allowed, opp_pass_epa_allowed_rank, opp_pass_yds_allowed_rank, opp_yds_per_dropback_rank, opp_sos_adj_pass_yds_allowed, opp_yds_per_dropback_allowed, opp_explosive_pass_rate_allowed
