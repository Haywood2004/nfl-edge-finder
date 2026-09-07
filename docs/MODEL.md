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
