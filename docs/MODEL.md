# MODEL.md — passing yards (py-lgbm-v1)

Last retrain: 2026-09-02 22:12 UTC · model_run id 2

## Protocol

Walk-forward: train 2016–2022 → validate 2023 (early stopping, scale calibration) → test 2024–2025. Production artifact refit on all seasons with the validated iteration count. Target = passing yards in games with ≥10 attempts. Distribution = Normal(mean, heteroscedastic sd). Mean model iterations 169, scale calibration k=1.025.

## Holdout (2024–2025)

| metric | value |
|---|---|
| games | 1129 |
| MAE (model) | 57.98 |
| RMSE | 72.76 |
| MAE baseline: EWM of player's yards | 60.28 |
| MAE baseline: previous-season avg | 64.52 |
| MAE proxy market (player-only LGBM) | 59.42 |
| q10 / q25 / q75 / q90 coverage | 0.095 / 0.273 / 0.781 / 0.917 (ideal .10/.25/.75/.90) |

### P(over) calibration at synthetic lines (holdout)

| predicted bucket | n | mean predicted | actual over rate |
|---|---|---|---|
| (0.2, 0.3] | 877 | 0.289 | 0.270 |
| (0.3, 0.4] | 1296 | 0.373 | 0.341 |
| (0.4, 0.5] | 2343 | 0.466 | 0.431 |
| (0.5, 0.6] | 1705 | 0.564 | 0.519 |
| (0.6, 0.7] | 1186 | 0.650 | 0.639 |
| (0.7, 0.8] | 496 | 0.707 | 0.683 |

Note: predicted P(over) runs 2–4 points above the realised over rate in every bucket — the model's mean is slightly high (it over-predicts early-season games by ~12 yds in 2024–25). The market anchor in scoring (DECISIONS #7) partly offsets this; a bias term is on the TODO list.

### Simulated betting vs PROXY market (holdout) — NOT real closing lines

Lines = proxy model median (player-only features, no opponent/context) ± 0.5; price −110 both sides. This measures whether matchup/context features add information over a 'the book knows the average' line. Real closing-line ROI accrues in the track record from live snapshots only.

| min edge | bets | wins | win rate | ROI |
|---|---|---|---|---|
| =0.02 | 900 | 525 | 0.583 | +0.114 |
| =0.04 | 663 | 401 | 0.605 | +0.155 |
| =0.06 | 460 | 289 | 0.628 | +0.199 |
| =0.08 | 293 | 195 | 0.666 | +0.271 |

## Validation (2023)

MAE 59.09 · coverage q25 0.234 / q75 0.727

## Top features (gain share)

| feature | share |
|---|---|
| py_ewm | 0.202 |
| implied_total | 0.092 |
| epa_att_ewm | 0.092 |
| total_line | 0.042 |
| days_since_last | 0.030 |
| wind | 0.026 |
| py_std_avg | 0.023 |
| team_pass_yds_pg | 0.022 |
| py_l5 | 0.022 |
| py_prev_season | 0.019 |
| opp_pass_epa_allowed | 0.018 |
| team_games | 0.017 |
| rush_yds_ewm | 0.016 |
| temp | 0.016 |
| att_l5 | 0.015 |
| sack_rate_ewm | 0.015 |
| py_sd_l10 | 0.014 |
| opp_rush_yds_allowed_pg | 0.014 |
| opp_games | 0.014 |
| air_yds_ewm | 0.014 |
| att_ewm | 0.014 |
| opp_sos_adj_pass_yds_allowed | 0.014 |
| opp_te_yds_allowed_pg | 0.013 |
| opp_pass_yds_allowed_pg | 0.012 |
| team_pass_rate | 0.012 |

All 58 features: dome, temp, wind, py_l3, py_l5, att_l3, att_l5, py_ewm, py_l10, att_ewm, is_home, ypa_ewm, ypa_l10, cpoe_ewm, div_game, new_team, week_num, games_std, opp_games, primetime, py_sd_l10, rest_days, team_proe, py_std_avg, team_games, total_line, air_yds_ewm, epa_att_ewm, spread_team, usage_trend, games_career, rush_yds_ewm, implied_total, opp_sack_rate, sack_rate_ewm, team_plays_pg, py_prev_season, team_pass_rate, days_since_last, team_pass_yds_pg, games_prev_season, team_epa_per_play, opp_pass_epa_allowed, opp_rush_epa_allowed, team_pass_epa_per_db, opp_sos_adj_pass_rank, opp_te_yds_allowed_pg, opp_wr_yds_allowed_pg, opp_dropbacks_faced_pg, opp_pass_yds_allowed_pg, opp_rush_yds_allowed_pg, opp_yac_per_comp_allowed, opp_pass_epa_allowed_rank, opp_pass_yds_allowed_rank, opp_yds_per_dropback_rank, opp_sos_adj_pass_yds_allowed, opp_yds_per_dropback_allowed, opp_explosive_pass_rate_allowed
