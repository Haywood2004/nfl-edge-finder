# MODEL.md — passing yards (py-lgbm-v2)

Last retrain: 2026-09-05 17:43 UTC · model_run id 44

## Protocol

Walk-forward: train 2016–2022 → validate 2023 (early stopping, scale calibration) → test 2024–2025. Production artifact refit on all seasons with the validated iteration count. Target = passing yards in games with ≥10 attempts, modelled RELATIVE to the previous season's league-average starter passing yards (v2; removes the era-drift bias that over-projected 2024–25 by 6–9 yds). Distribution = mean + heteroscedastic sd × empirical standardised-residual distribution (v2; replaces the Normal). Mean model iterations 328, scale calibration k=1.075.

v2 feature additions: coaching-regime flag (new head coach → league-average tendency priors), script-neutral pass rate / pace / shotgun / no-huddle rates, injury context (own skill & OL outs, share of prior targets ruled out, WR1 out; opponent DB and front-seven outs) from 2016–2025 official reports + live ESPN feed, and league passing environment (rolling 8-week and prior-season means).

## Holdout (2024–2025)

| metric | value |
|---|---|
| games | 1129 |
| MAE (model) | 57.89 |
| RMSE | 72.74 |
| MAE baseline: EWM of player's yards | 60.28 |
| MAE baseline: previous-season avg | 64.52 |
| MAE proxy market (player-only LGBM) | 59.13 |
| q10 / q25 / q75 / q90 coverage | 0.115 / 0.269 / 0.753 / 0.905 (ideal .10/.25/.75/.90) |

### P(over) calibration at synthetic lines (holdout)

| predicted bucket | n | mean predicted | actual over rate |
|---|---|---|---|
| (0.2, 0.3] | 974 | 0.276 | 0.281 |
| (0.3, 0.4] | 1124 | 0.378 | 0.364 |
| (0.4, 0.5] | 2418 | 0.467 | 0.441 |
| (0.5, 0.6] | 1693 | 0.562 | 0.545 |
| (0.6, 0.7] | 946 | 0.640 | 0.625 |
| (0.7, 0.8] | 748 | 0.712 | 0.698 |

### Simulated betting vs PROXY market (holdout) — NOT real closing lines

Lines = proxy model median (player-only features, no opponent/context) ± 0.5; price −110 both sides. This measures whether matchup/context features add information over a 'the book knows the average' line. Real closing-line ROI accrues in the track record from live snapshots only.

| min edge | bets | wins | win rate | ROI |
|---|---|---|---|---|
| =0.02 | 917 | 526 | 0.574 | +0.095 |
| =0.04 | 726 | 423 | 0.583 | +0.112 |
| =0.06 | 581 | 343 | 0.590 | +0.127 |
| =0.08 | 406 | 251 | 0.618 | +0.180 |

## Validation (2023)

MAE 59.38 · coverage q25 0.245 / q75 0.715

## Top features (gain share)

| feature | share |
|---|---|
| py_ewm | 0.171 |
| implied_total | 0.090 |
| epa_att_ewm | 0.082 |
| league_py_prev_season | 0.047 |
| total_line | 0.044 |
| py_l5 | 0.040 |
| py_std_avg | 0.037 |
| wind | 0.028 |
| days_since_last | 0.027 |
| py_prev_season | 0.024 |
| week_num | 0.017 |
| opp_pass_epa_allowed | 0.016 |
| team_neutral_pass_rate | 0.016 |
| py_l10 | 0.015 |
| opp_games | 0.014 |
| team_plays_pg | 0.013 |
| team_pass_yds_pg | 0.012 |
| opp_rush_yds_allowed_pg | 0.012 |
| opp_sos_adj_pass_yds_allowed | 0.012 |
| py_sd_l10 | 0.012 |
| sack_rate_ewm | 0.011 |
| team_games | 0.011 |
| opp_pass_yds_allowed_pg | 0.010 |
| opp_yds_per_dropback_allowed | 0.010 |
| att_ewm | 0.010 |

All 74 features: dome, temp, wind, py_l3, py_l5, att_l3, att_l5, new_hc, ol_out, py_ewm, py_l10, att_ewm, is_home, wr1_out, ypa_ewm, ypa_l10, cpoe_ewm, div_game, new_team, week_num, games_std, opp_games, primetime, py_sd_l10, rest_days, skill_out, team_proe, opp_db_out, py_std_avg, team_games, total_line, air_yds_ewm, epa_att_ewm, spread_team, usage_trend, coach_tenure, games_career, league_py_l8, rush_yds_ewm, implied_total, league_att_l8, opp_front_out, opp_sack_rate, sack_rate_ewm, team_plays_pg, py_prev_season, team_pass_rate, days_since_last, target_share_out, team_pass_yds_pg, games_prev_season, team_epa_per_play, team_shotgun_rate, injury_report_seen, team_no_huddle_rate, opp_pass_epa_allowed, opp_rush_epa_allowed, team_pass_epa_per_db, league_py_prev_season, opp_sos_adj_pass_rank, opp_te_yds_allowed_pg, opp_wr_yds_allowed_pg, team_neutral_plays_pg, opp_dropbacks_faced_pg, team_neutral_pass_rate, opp_pass_yds_allowed_pg, opp_rush_yds_allowed_pg, opp_yac_per_comp_allowed, opp_pass_epa_allowed_rank, opp_pass_yds_allowed_rank, opp_yds_per_dropback_rank, opp_sos_adj_pass_yds_allowed, opp_yds_per_dropback_allowed, opp_explosive_pass_rate_allowed

# MODEL.md — live (in-game)

_Replay of 2025 play-by-play, 272 games, 2026-09-07 00:07 UTC. `python -m live replay`. Pre-game priors = the pipeline models on 2025 feature rows (held-out season)._

MAE of the projected FINAL stat at each checkpoint. `live` = the in-game model (live/ingame.py); `pregame` = the pre-game mean; `naive_pace` = y_t / f; `no_adj` = y_t + (1−f)·mean (no usage / game-script adjustment). `cover_1sd` = share of finals within ±1 sd_live (0.68 if calibrated); `z_sd` = sd of the standardised error (1.0 if calibrated).

| market | checkpoint | n | live | pregame | naive_pace | no_adj | cover_1sd | z_sd |
|---|---|---|---|---|---|---|---|---|
| player_pass_yds | end Q1 | 561 | **48.3** | 51.0 | 92.8 | 47.7 | 0.72 | 0.96 |
| player_pass_yds | end Q2 | 548 | **39.8** | 50.2 | 55.6 | 42.2 | 0.70 | 0.95 |
| player_pass_yds | end Q3 | 557 | **30.0** | 50.6 | 38.0 | 34.1 | 0.73 | 0.97 |
| player_pass_yds | Q4 5:00 | 561 | **19.2** | 51.0 | 22.3 | 21.9 | 0.78 | 1.00 |
| player_reception_yds | end Q1 | 3320 | **17.1** | 19.5 | 29.2 | 17.2 | 0.78 | 0.96 |
| player_reception_yds | end Q2 | 2703 | **14.1** | 20.4 | 19.6 | 14.5 | 0.82 | 0.98 |
| player_reception_yds | end Q3 | 3016 | **9.2** | 19.9 | 10.9 | 9.9 | 0.85 | 1.00 |
| player_reception_yds | Q4 5:00 | 3163 | **4.6** | 19.7 | 5.1 | 5.1 | 0.88 | 1.06 |
| player_receptions | end Q1 | 3320 | **1.3** | 1.4 | 2.3 | 1.3 | 0.71 | 1.02 |
| player_receptions | end Q2 | 2703 | **1.0** | 1.4 | 1.4 | 1.1 | 0.73 | 0.99 |
| player_receptions | end Q3 | 3016 | **0.7** | 1.4 | 0.8 | 0.8 | 0.81 | 0.99 |
| player_receptions | Q4 5:00 | 3163 | **0.4** | 1.4 | 0.4 | 0.4 | 0.84 | 1.03 |
| player_rush_yds | end Q1 | 1020 | **20.3** | 23.4 | 32.1 | 20.6 | 0.74 | 1.00 |
| player_rush_yds | end Q2 | 944 | **16.5** | 23.7 | 18.9 | 16.7 | 0.74 | 1.04 |
| player_rush_yds | end Q3 | 979 | **11.1** | 23.6 | 11.0 | 11.1 | 0.75 | 1.13 |
| player_rush_yds | Q4 5:00 | 997 | **5.0** | 23.5 | 4.9 | 5.1 | 0.89 | 0.94 |

Reading: the live model should beat both baselines at every checkpoint and by a widening margin as the game goes on; `no_adj` vs `live` isolates what the usage and game-script terms add. If `z_sd` > 1 the live sd is too tight (raise LIVE_INGAME_SD_FLOOR); if < 1 it is too wide.

# MODEL.md — passing yards vs REAL closing lines

Run: 2026-09-07 20:16 UTC · seasons [2023, 2024, 2025] · level anchor 1.0 · player anchor 0.2

Closing lines (kickoff − 60 min) from The Odds API historical endpoints, every US book, each book's main line. Model fit walk-forward (train < S−1, validate S−1, refit mean < S). 1u flat on every side with edge ≥ threshold at the best price.

## Overall

| min edge | bets | W-L-P | win rate | units | ROI | avg price |
|---|---|---|---|---|---|---|
| =0.00 | 1767 | 939-828-0 | 0.531 | +16.4 | +0.009 | 1.899 |
| =0.02 | 1163 | 623-540-0 | 0.536 | +20.5 | +0.018 | 1.900 |
| =0.04 | 695 | 374-321-0 | 0.538 | +15.4 | +0.022 | 1.899 |
| =0.06 | 428 | 219-209-0 | 0.512 | -11.9 | -0.028 | 1.899 |
| =0.08 | 233 | 122-111-0 | 0.524 | -1.1 | -0.005 | 1.898 |
| =0.10 | 103 | 51-52-0 | 0.495 | -5.8 | -0.056 | 1.900 |
| =0.15 | 18 | 9-9-0 | 0.500 | -0.9 | -0.050 | 1.897 |

## 2023

| min edge | bets | W-L-P | win rate | units | ROI | avg price |
|---|---|---|---|---|---|---|
| =0.00 | 601 | 317-284-0 | 0.527 | +2.1 | +0.004 | 1.903 |
| =0.02 | 382 | 203-179-0 | 0.531 | +4.2 | +0.011 | 1.904 |
| =0.04 | 211 | 116-95-0 | 0.550 | +9.6 | +0.046 | 1.903 |
| =0.06 | 126 | 65-61-0 | 0.516 | -2.4 | -0.019 | 1.903 |
| =0.08 | 63 | 32-31-0 | 0.508 | -1.9 | -0.030 | 1.903 |
| =0.10 | 30 | 16-14-0 | 0.533 | +0.8 | +0.025 | 1.909 |
| =0.15 | 4 | 2-2-0 | 0.500 | -0.2 | -0.045 | 1.890 |

## 2024

| min edge | bets | W-L-P | win rate | units | ROI | avg price |
|---|---|---|---|---|---|---|
| =0.00 | 568 | 310-258-0 | 0.546 | +22.7 | +0.040 | 1.904 |
| =0.02 | 410 | 229-181-0 | 0.559 | +26.4 | +0.064 | 1.904 |
| =0.04 | 247 | 143-104-0 | 0.579 | +25.4 | +0.103 | 1.904 |
| =0.06 | 163 | 93-70-0 | 0.571 | +14.2 | +0.087 | 1.903 |
| =0.08 | 87 | 52-35-0 | 0.598 | +12.0 | +0.138 | 1.901 |
| =0.10 | 38 | 23-15-0 | 0.605 | +5.8 | +0.152 | 1.902 |
| =0.15 | 8 | 4-4-0 | 0.500 | -0.4 | -0.050 | 1.905 |

## 2025

| min edge | bets | W-L-P | win rate | units | ROI | avg price |
|---|---|---|---|---|---|---|
| =0.00 | 598 | 312-286-0 | 0.522 | -8.4 | -0.014 | 1.890 |
| =0.02 | 371 | 191-180-0 | 0.515 | -10.1 | -0.027 | 1.890 |
| =0.04 | 237 | 115-122-0 | 0.485 | -19.7 | -0.083 | 1.890 |
| =0.06 | 139 | 61-78-0 | 0.439 | -23.7 | -0.171 | 1.890 |
| =0.08 | 83 | 38-45-0 | 0.458 | -11.2 | -0.135 | 1.891 |
| =0.10 | 35 | 12-23-0 | 0.343 | -12.3 | -0.352 | 1.891 |
| =0.15 | 6 | 3-3-0 | 0.500 | -0.3 | -0.053 | 1.890 |

## By side (overall)

**Over**

| min edge | bets | W-L-P | win rate | units | ROI | avg price |
|---|---|---|---|---|---|---|
| =0.00 | 889 | 479-410-0 | 0.539 | +22.9 | +0.026 | 1.903 |
| =0.04 | 348 | 195-153-0 | 0.560 | +23.5 | +0.068 | 1.904 |
| =0.08 | 114 | 61-53-0 | 0.535 | +2.3 | +0.020 | 1.902 |

**Under**

| min edge | bets | W-L-P | win rate | units | ROI | avg price |
|---|---|---|---|---|---|---|
| =0.00 | 878 | 460-418-0 | 0.524 | -6.4 | -0.007 | 1.895 |
| =0.04 | 347 | 179-168-0 | 0.516 | -8.1 | -0.023 | 1.894 |
| =0.08 | 119 | 61-58-0 | 0.513 | -3.4 | -0.028 | 1.894 |

## Calibration at real lines

| model p bucket | n | mean p | hit rate |
|---|---|---|---|
| (0.0, 0.4] | 66 | 0.366 | 0.455 |
| (0.4, 0.45] | 332 | 0.429 | 0.488 |
| (0.45, 0.5] | 1017 | 0.479 | 0.463 |
| (0.5, 0.55] | 1226 | 0.521 | 0.535 |
| (0.55, 0.6] | 430 | 0.571 | 0.540 |
| (0.6, 0.65] | 84 | 0.618 | 0.464 |
| (0.65, 0.7] | 12 | 0.677 | 0.500 |
| (0.7, 1.0] | 5 | 0.742 | 0.600 |

## Anchor-weight grid (ROI at edge ≥ 4%, all seasons)

| level \ player anchor | 0.00 | 0.20 | 0.35 | 0.50 | 0.70 |
|---|---|---|---|---|---|
| 0.0 | -0.006 (930) | +0.007 (805) | +0.012 (656) | -0.003 (472) | +0.081 (169) |
| 0.5 | -0.001 (857) | +0.015 (727) | +0.010 (582) | -0.004 (404) | -0.025 (137) |
| 1.0 | +0.025 (832) | +0.022 (695) | +0.022 (563) | -0.033 (399) | -0.073 (124) |

# MODEL.md — spreads & totals (spread-ridge-v1)

Last retrain: 2026-09-12 04:01 UTC · model_run id 49

Ridge regression for the home margin on Elo diff (home field included), EPA rating diff, rest diff, divisional, neutral site, QB change, QB inexperience and an early-season flag; a second ridge for the game total. Walk-forward: every season 2019–2025 is predicted by a model fit on the seasons before it. Residual sd 13.10 pts. Anchor weight toward the closing spread chosen on 2024 by MAE: **0.90** (total: 0.70).

Standardised coefficients: elo_diff +2.690, epa_diff +2.684, rest_diff +0.348, div_game -0.142, neutral -0.158, qb_change_diff -1.017, qb_inexp_diff +0.753, early_season -0.128

## Walk-forward 2019–2025 — RAW model vs the closing spread (nflverse)

MAE model **10.22** vs market **9.83** · straight-up 0.642 vs 0.662 · n=1871

| min gap | bets | W-L-P | win rate | units (−110) | ROI |
|---|---|---|---|---|---|
| 0 pts | 1871 | 881-947-43 | 0.482 | -146.1 | -0.078 |
| 1 pts | 1304 | 621-653-30 | 0.487 | -88.5 | -0.068 |
| 2 pts | 832 | 376-437-19 | 0.462 | -95.2 | -0.114 |
| 3 pts | 497 | 222-266-9 | 0.455 | -64.2 | -0.129 |
| 4 pts | 278 | 141-134-3 | 0.513 | -5.8 | -0.021 |
| 5 pts | 139 | 76-62-1 | 0.551 | +7.1 | +0.051 |
| 7 pts | 50 | 27-23-0 | 0.540 | +1.5 | +0.031 |

## Test 2025 — RAW model

MAE model 10.33 vs market 9.72 · n=272

| min gap | bets | W-L-P | win rate | units (−110) | ROI |
|---|---|---|---|---|---|
| 0 pts | 272 | 122-149-1 | 0.450 | -38.1 | -0.140 |
| 1 pts | 190 | 85-104-1 | 0.450 | -26.7 | -0.141 |
| 2 pts | 115 | 44-71-0 | 0.383 | -31.0 | -0.270 |
| 3 pts | 74 | 28-46-0 | 0.378 | -20.5 | -0.278 |
| 4 pts | 43 | 16-27-0 | 0.372 | -12.5 | -0.290 |
| 5 pts | 19 | 6-13-0 | 0.316 | -7.5 | -0.397 |
| 7 pts | 8 | 2-6-0 | 0.250 | -4.2 | -0.523 |

## Weeks 1–4 vs weeks 5+ (walk-forward, RAW) — where a ratings model can and cannot beat the line

Weeks 1–4: MAE 10.22 vs 9.62

| min gap | bets | W-L-P | win rate | units (−110) | ROI |
|---|---|---|---|---|---|
| 0 pts | 446 | 186-250-10 | 0.427 | -80.9 | -0.181 |
| 1 pts | 320 | 140-174-6 | 0.446 | -46.7 | -0.146 |
| 2 pts | 216 | 94-118-4 | 0.443 | -32.5 | -0.151 |
| 3 pts | 138 | 56-80-2 | 0.412 | -29.1 | -0.211 |
| 4 pts | 82 | 41-41-0 | 0.500 | -3.7 | -0.045 |
| 5 pts | 40 | 23-17-0 | 0.575 | +3.9 | +0.098 |
| 7 pts | 14 | 8-6-0 | 0.571 | +1.3 | +0.091 |

Weeks 5+: MAE 10.22 vs 9.89

| min gap | bets | W-L-P | win rate | units (−110) | ROI |
|---|---|---|---|---|---|
| 0 pts | 1425 | 695-697-33 | 0.499 | -65.2 | -0.046 |
| 1 pts | 984 | 481-479-24 | 0.501 | -41.7 | -0.042 |
| 2 pts | 616 | 282-319-15 | 0.469 | -62.6 | -0.102 |
| 3 pts | 359 | 166-186-7 | 0.472 | -35.1 | -0.098 |
| 4 pts | 196 | 100-93-3 | 0.518 | -2.1 | -0.011 |
| 5 pts | 99 | 53-45-1 | 0.541 | +3.2 | +0.032 |
| 7 pts | 36 | 19-17-0 | 0.528 | +0.3 | +0.008 |

## By season (RAW, gap ≥ 3)

| season | MAE model | MAE market | bets | W-L-P | units |
|---|---|---|---|---|---|
| 2019 | 10.64 | 10.21 | 73 | 32-38-3 | -8.9 |
| 2020 | 10.03 | 9.83 | 60 | 27-33-0 | -8.5 |
| 2021 | 11.21 | 10.78 | 85 | 39-45-1 | -9.5 |
| 2022 | 9.04 | 8.74 | 71 | 34-35-2 | -4.1 |
| 2023 | 10.35 | 9.90 | 56 | 23-32-1 | -11.1 |
| 2024 | 9.93 | 9.61 | 78 | 39-37-2 | -1.5 |
| 2025 | 10.33 | 9.72 | 74 | 28-46-0 | -20.5 |

The /games page shows the blended projection (what we would actually bet off) and the raw one. Spread picks are flagged as bets only where the table above shows the gap bucket is profitable out of sample; otherwise the pick is shown as a lean with no stake, exactly like the moneyline layer.
