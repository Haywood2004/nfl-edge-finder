# MODEL.md — passing yards (py-lgbm-v1)

Last retrain: 2026-09-02 23:15 UTC · model_run id 2

## Protocol

Walk-forward: train 2016–2022 → validate 2023 (early stopping, scale calibration) → test 2024–2025. Production artifact refit on all seasons with the validated iteration count. Target = passing yards in games with ≥10 attempts. Distribution = Normal(mean, heteroscedastic sd). Mean model iterations 260, scale calibration k=1.050.

## Holdout (2024–2025)

| metric | value |
|---|---|
| games | 1129 |
| MAE (model) | 57.84 |
| RMSE | 72.66 |
| MAE baseline: EWM of player's yards | 60.28 |
| MAE baseline: previous-season avg | 64.52 |
| MAE proxy market (player-only LGBM) | 59.26 |
| q10 / q25 / q75 / q90 coverage | 0.090 / 0.277 / 0.787 / 0.922 (ideal .10/.25/.75/.90) |

### P(over) calibration at synthetic lines (holdout)

| predicted bucket | n | mean predicted | actual over rate |
|---|---|---|---|
| (0.2, 0.3] | 742 | 0.288 | 0.282 |
| (0.3, 0.4] | 1375 | 0.367 | 0.327 |
| (0.4, 0.5] | 2399 | 0.465 | 0.424 |
| (0.5, 0.6] | 1767 | 0.564 | 0.529 |
| (0.6, 0.7] | 1198 | 0.654 | 0.639 |
| (0.7, 0.8] | 422 | 0.708 | 0.671 |

### Simulated betting vs PROXY market (holdout) — NOT real closing lines

Lines = proxy model median (player-only features, no opponent/context) ± 0.5; price −110 both sides. This measures whether matchup/context features add information over a 'the book knows the average' line. Real closing-line ROI accrues in the track record from live snapshots only.

| min edge | bets | wins | win rate | ROI |
|---|---|---|---|---|
| =0.02 | 874 | 505 | 0.578 | +0.103 |
| =0.04 | 631 | 374 | 0.593 | +0.132 |
| =0.06 | 445 | 276 | 0.620 | +0.184 |
| =0.08 | 290 | 183 | 0.631 | +0.205 |

## Validation (2023)

MAE 59.14 · coverage q25 0.243 / q75 0.745

## Top features (gain share)

| feature | share |
|---|---|
| py_ewm | 0.163 |
| implied_total | 0.081 |
| epa_att_ewm | 0.073 |
| total_line | 0.036 |
| days_since_last | 0.028 |
| wind | 0.027 |
| py_std_avg | 0.021 |
| py_prev_season | 0.021 |
| py_l5 | 0.019 |
| py_l10 | 0.019 |
| team_pass_yds_pg | 0.019 |
| opp_sos_adj_pass_yds_allowed | 0.018 |
| sack_rate_ewm | 0.018 |
| att_l5 | 0.017 |
| rush_yds_ewm | 0.016 |
| opp_pass_epa_allowed | 0.016 |
| opp_yds_per_dropback_allowed | 0.016 |
| opp_games | 0.016 |
| usage_trend | 0.016 |
| team_plays_pg | 0.016 |
| week_num | 0.016 |
| py_sd_l10 | 0.015 |
| opp_yac_per_comp_allowed | 0.015 |
| opp_rush_yds_allowed_pg | 0.015 |
| air_yds_ewm | 0.015 |

All 58 features: dome, temp, wind, py_l3, py_l5, att_l3, att_l5, py_ewm, py_l10, att_ewm, is_home, ypa_ewm, ypa_l10, cpoe_ewm, div_game, new_team, week_num, games_std, opp_games, primetime, py_sd_l10, rest_days, team_proe, py_std_avg, team_games, total_line, air_yds_ewm, epa_att_ewm, spread_team, usage_trend, games_career, rush_yds_ewm, implied_total, opp_sack_rate, sack_rate_ewm, team_plays_pg, py_prev_season, team_pass_rate, days_since_last, team_pass_yds_pg, games_prev_season, team_epa_per_play, opp_pass_epa_allowed, opp_rush_epa_allowed, team_pass_epa_per_db, opp_sos_adj_pass_rank, opp_te_yds_allowed_pg, opp_wr_yds_allowed_pg, opp_dropbacks_faced_pg, opp_pass_yds_allowed_pg, opp_rush_yds_allowed_pg, opp_yac_per_comp_allowed, opp_pass_epa_allowed_rank, opp_pass_yds_allowed_rank, opp_yds_per_dropback_rank, opp_sos_adj_pass_yds_allowed, opp_yds_per_dropback_allowed, opp_explosive_pass_rate_allowed

# MODEL.md — moneyline (ml-logit-v1)

Last retrain: 2026-09-03 00:05 UTC · model_run id 37

Logistic regression on Elo diff (home field included), EPA rating diff, rest diff, divisional, neutral site, QB change and QB inexperience. Train 2016–2023 → validate 2024 (anchor weight) → test 2025. Anchor weight toward the no-vig market: **0.95** (chosen by validation log-loss).

Standardised coefficients: elo_diff +0.447, epa_diff +0.238, rest_diff +0.085, div_game -0.019, neutral -0.069, qb_change_diff -0.131, qb_inexp_diff +0.121

## Test 2025 — REAL closing moneylines (nflverse)

| metric | model | market | blend |
|---|---|---|---|
| log-loss | 0.6359 | 0.6082 | 0.6090 |
| accuracy | 0.621 | 0.658 | – |

### Betting at the closing price (2025, blend)

| min edge | bets | wins | win rate | units | ROI |
|---|---|---|---|---|---|
| >=0.02 | 0 | 0 | 0.000 | +0.00 | +0.000 |
| >=0.04 | 0 | 0 | 0.000 | +0.00 | +0.000 |
| >=0.06 | 0 | 0 | 0.000 | +0.00 | +0.000 |
| >=0.08 | 0 | 0 | 0.000 | +0.00 | +0.000 |
| >=0.10 | 0 | 0 | 0.000 | +0.00 | +0.000 |
| >=0.15 | 0 | 0 | 0.000 | +0.00 | +0.000 |

### Walk-forward 2019–2025 (model trained on 2016–2018 only, blend)

| min edge | bets | wins | win rate | units | ROI |
|---|---|---|---|---|---|
| >=0.02 | 3 | 1 | 0.333 | -0.78 | -0.260 |
| >=0.04 | 0 | 0 | 0.000 | +0.00 | +0.000 |
| >=0.06 | 0 | 0 | 0.000 | +0.00 | +0.000 |
| >=0.08 | 0 | 0 | 0.000 | +0.00 | +0.000 |
| >=0.10 | 0 | 0 | 0.000 | +0.00 | +0.000 |
| >=0.15 | 0 | 0 | 0.000 | +0.00 | +0.000 |

### Why the anchor is 0.95 — the RAW ratings model bet against closing lines, 2019–2025

Every 'edge' the un-anchored model sees against a closing NFL moneyline loses money, including the biggest ones. That is the reason moneyline cards are only flagged for price discrepancies between venues, not for model-vs-market disagreement.

| min edge | bets | wins | win rate | units | ROI |
|---|---|---|---|---|---|
| >=0.02 | 1510 | 707 | 0.468 | -145.36 | -0.096 |
| >=0.04 | 1192 | 546 | 0.458 | -143.56 | -0.120 |
| >=0.06 | 892 | 405 | 0.454 | -102.67 | -0.115 |
| >=0.08 | 641 | 279 | 0.435 | -78.20 | -0.122 |
| >=0.10 | 435 | 185 | 0.425 | -48.79 | -0.112 |
| >=0.15 | 176 | 66 | 0.375 | -24.47 | -0.139 |

### Calibration (2025, blend)

| bucket | n | predicted | actual |
|---|---|---|---|
| (0.0, 0.3] | 34 | 0.227 | 0.206 |
| (0.3, 0.4] | 37 | 0.351 | 0.432 |
| (0.4, 0.5] | 44 | 0.447 | 0.409 |
| (0.5, 0.6] | 44 | 0.556 | 0.591 |
| (0.6, 0.7] | 45 | 0.646 | 0.511 |
| (0.7, 1.0] | 68 | 0.797 | 0.824 |

Validation 2024: log-loss model 0.6021 vs market 0.5875.
