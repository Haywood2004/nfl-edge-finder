# L3 experiment — generated backtest (do not edit; `python -m nfl_edge backtest_l3`)

Generated 2026-10-04T04:44 UTC. Closing lines from `pipeline/fixtures/odds_history`, DK/FD/Pinnacle only, graded at the best closing price among those books at the modal line. Opening prices are not in the fixtures, so there is no opening-price grade or backtest CLV yet.

Lines available: {"player_pass_yds": [2023, 2024, 2025], "player_rush_yds": [2025]}

## Base rate (share of priced lines that went Over)

| market | lines | over rate |
|---|---|---|
| player_pass_yds | 1300 | 52.0% |
| player_rush_yds | 725 | 49.1% |

Every row: weeks ≥ 4 only (the last-3 inputs need 3 games played).


## Results at a flat −110 on every pick (1u)

| version · market · split | W-L-P | hit | ROI | units | 95% CI ROI | t |
|---|---|---|---|---|---|---|
| l3_v1 · all | 21-17-0 | 55.3% | +5.5% | +2.1u | [-25.1%, +36.1%] | 0.35 |
| l3_v1 · player_pass_yds | 12-10-0 | 54.5% | +4.1% | +0.9u | [-36.5%, +44.8%] | 0.20 |
| l3_v1 · player_pass_yds · Over | 8-6-0 | 57.1% | +9.1% | +1.3u | [-42.3%, +60.4%] | 0.35 |
| l3_v1 · player_pass_yds · Under | 4-4-0 | 50.0% | -4.5% | -0.4u | [-75.3%, +66.2%] | -0.13 |
| l3_v1 · player_rush_yds | 9-7-0 | 56.2% | +7.4% | +1.2u | [-40.5%, +55.3%] | 0.30 |
| l3_v1 · player_rush_yds · Over | 8-7-0 | 53.3% | +1.8% | +0.3u | [-48.1%, +51.7%] | 0.07 |
| l3_v1 · player_rush_yds · Under | 1-0-0 | 100.0% | +90.9% | +0.9u | – | – |
| naive_g10 · all | 120-116-0 | 50.8% | -2.9% | -6.9u | [-15.1%, +9.3%] | -0.47 |
| naive_g10 · player_pass_yds | 61-53-0 | 53.5% | +2.2% | +2.5u | [-15.4%, +19.7%] | 0.24 |
| naive_g10 · player_pass_yds · Over | 32-28-0 | 53.3% | +1.8% | +1.1u | [-22.5%, +26.1%] | 0.15 |
| naive_g10 · player_pass_yds · Under | 29-25-0 | 53.7% | +2.5% | +1.4u | [-23.1%, +28.2%] | 0.19 |
| naive_g10 · player_rush_yds | 59-63-0 | 48.4% | -7.7% | -9.4u | [-24.7%, +9.3%] | -0.88 |
| naive_g10 · player_rush_yds · Over | 35-41-0 | 46.1% | -12.1% | -9.2u | [-33.6%, +9.5%] | -1.10 |
| naive_g10 · player_rush_yds · Under | 24-22-0 | 52.2% | -0.4% | -0.2u | [-28.3%, +27.5%] | -0.03 |
| naive_v0 · all | 197-201-0 | 49.5% | -5.5% | -21.9u | [-14.9%, +3.9%] | -1.15 |
| naive_v0 · player_pass_yds | 124-121-0 | 50.6% | -3.4% | -8.3u | [-15.4%, +8.6%] | -0.55 |
| naive_v0 · player_pass_yds · Over | 73-60-0 | 54.9% | +4.8% | +6.4u | [-11.4%, +21.0%] | 0.58 |
| naive_v0 · player_pass_yds · Under | 51-61-0 | 45.5% | -13.1% | -14.6u | [-30.8%, +4.6%] | -1.45 |
| naive_v0 · player_rush_yds | 73-80-0 | 47.7% | -8.9% | -13.6u | [-24.1%, +6.2%] | -1.15 |
| naive_v0 · player_rush_yds · Over | 42-48-0 | 46.7% | -10.9% | -9.8u | [-30.7%, +8.9%] | -1.08 |
| naive_v0 · player_rush_yds · Under | 31-32-0 | 49.2% | -6.1% | -3.8u | [-29.8%, +17.7%] | -0.50 |

## Results (1u flat, best actual closing price)

| version · market · split | W-L-P | hit | ROI | units | 95% CI ROI | t |
|---|---|---|---|---|---|---|
| l3_v1 · all | 21-17-0 | 55.3% | +4.6% | +1.7u | [-25.7%, +34.9%] | 0.30 |
| l3_v1 · player_pass_yds | 12-10-0 | 54.5% | +3.0% | +0.7u | [-37.2%, +43.3%] | 0.15 |
| l3_v1 · player_pass_yds · 2023 | 4-5-0 | 44.4% | -15.8% | -1.4u | [-81.0%, +49.5%] | -0.47 |
| l3_v1 · player_pass_yds · 2024 | 3-2-0 | 60.0% | +13.0% | +0.7u | [-77.4%, +103.4%] | 0.28 |
| l3_v1 · player_pass_yds · 2025 | 5-3-0 | 62.5% | +18.0% | +1.4u | [-49.7%, +85.7%] | 0.52 |
| l3_v1 · player_pass_yds · Over | 8-6-0 | 57.1% | +7.9% | +1.1u | [-42.9%, +58.6%] | 0.30 |
| l3_v1 · player_pass_yds · Under | 4-4-0 | 50.0% | -5.4% | -0.4u | [-75.5%, +64.7%] | -0.15 |
| l3_v1 · player_rush_yds | 9-7-0 | 56.2% | +6.7% | +1.1u | [-40.9%, +54.4%] | 0.28 |
| l3_v1 · player_rush_yds · 2025 | 9-7-0 | 56.2% | +6.7% | +1.1u | [-40.9%, +54.4%] | 0.28 |
| l3_v1 · player_rush_yds · Over | 8-7-0 | 53.3% | +1.3% | +0.2u | [-48.4%, +50.9%] | 0.05 |
| l3_v1 · player_rush_yds · Under | 1-0-0 | 100.0% | +89.0% | +0.9u | – | – |
| naive_g10 · all | 120-116-0 | 50.8% | -3.8% | -8.9u | [-15.9%, +8.3%] | -0.61 |
| naive_g10 · player_pass_yds | 61-53-0 | 53.5% | +1.4% | +1.6u | [-16.0%, +18.8%] | 0.16 |
| naive_g10 · player_pass_yds · 2023 | 17-13-0 | 56.7% | +7.6% | +2.3u | [-26.6%, +41.8%] | 0.43 |
| naive_g10 · player_pass_yds · 2024 | 20-26-0 | 43.5% | -17.5% | -8.0u | [-45.0%, +10.0%] | -1.25 |
| naive_g10 · player_pass_yds · 2025 | 24-14-0 | 63.2% | +19.4% | +7.4u | [-10.0%, +48.8%] | 1.29 |
| naive_g10 · player_pass_yds · Over | 32-28-0 | 53.3% | +0.9% | +0.5u | [-23.2%, +25.0%] | 0.07 |
| naive_g10 · player_pass_yds · Under | 29-25-0 | 53.7% | +2.0% | +1.1u | [-23.5%, +27.5%] | 0.15 |
| naive_g10 · player_rush_yds | 59-63-0 | 48.4% | -8.6% | -10.5u | [-25.4%, +8.2%] | -1.00 |
| naive_g10 · player_rush_yds · 2025 | 59-63-0 | 48.4% | -8.6% | -10.5u | [-25.4%, +8.2%] | -1.00 |
| naive_g10 · player_rush_yds · Over | 35-41-0 | 46.1% | -13.0% | -9.9u | [-34.3%, +8.4%] | -1.19 |
| naive_g10 · player_rush_yds · Under | 24-22-0 | 52.2% | -1.5% | -0.7u | [-29.0%, +26.1%] | -0.10 |
| naive_v0 · all | 197-201-0 | 49.5% | -6.3% | -25.0u | [-15.6%, +3.0%] | -1.32 |
| naive_v0 · player_pass_yds | 124-121-0 | 50.6% | -4.1% | -10.1u | [-16.0%, +7.8%] | -0.68 |
| naive_v0 · player_pass_yds · 2023 | 40-38-0 | 51.3% | -2.7% | -2.1u | [-23.9%, +18.5%] | -0.25 |
| naive_v0 · player_pass_yds · 2024 | 38-49-0 | 43.7% | -17.2% | -15.0u | [-37.1%, +2.7%] | -1.70 |
| naive_v0 · player_pass_yds · 2025 | 46-34-0 | 57.5% | +8.7% | +7.0u | [-11.9%, +29.4%] | 0.83 |
| naive_v0 · player_pass_yds · Over | 73-60-0 | 54.9% | +3.9% | +5.2u | [-12.2%, +19.9%] | 0.47 |
| naive_v0 · player_pass_yds · Under | 51-61-0 | 45.5% | -13.6% | -15.2u | [-31.2%, +4.0%] | -1.51 |
| naive_v0 · player_rush_yds | 73-80-0 | 47.7% | -9.8% | -15.0u | [-24.8%, +5.2%] | -1.28 |
| naive_v0 · player_rush_yds · 2025 | 73-80-0 | 47.7% | -9.8% | -15.0u | [-24.8%, +5.2%] | -1.28 |
| naive_v0 · player_rush_yds · Over | 42-48-0 | 46.7% | -11.8% | -10.6u | [-31.4%, +7.8%] | -1.18 |
| naive_v0 · player_rush_yds · Under | 31-32-0 | 49.2% | -6.9% | -4.3u | [-30.4%, +16.7%] | -0.57 |

## Calibration of l3_v1 P(over), deciles over every priced line

**player_pass_yds**

| decile | n | mean P(over) | actual over |
|---|---|---|---|
| 1 | 130 | 34.4% | 49.2% |
| 2 | 130 | 44.1% | 51.5% |
| 3 | 130 | 47.6% | 55.4% |
| 4 | 130 | 50.0% | 56.2% |
| 5 | 130 | 52.0% | 48.5% |
| 6 | 130 | 54.3% | 51.5% |
| 7 | 130 | 56.3% | 55.4% |
| 8 | 130 | 59.2% | 53.1% |
| 9 | 130 | 62.5% | 45.4% |
| 10 | 130 | 68.2% | 53.8% |

**player_rush_yds**

| decile | n | mean P(over) | actual over |
|---|---|---|---|
| 1 | 73 | 30.7% | 41.1% |
| 2 | 72 | 37.7% | 44.4% |
| 3 | 73 | 42.2% | 52.1% |
| 4 | 72 | 46.2% | 50.0% |
| 5 | 73 | 51.1% | 54.8% |
| 6 | 72 | 57.5% | 58.3% |
| 7 | 72 | 63.7% | 41.7% |
| 8 | 73 | 71.7% | 49.3% |
| 9 | 72 | 78.9% | 50.0% |
| 10 | 73 | 90.3% | 49.3% |

## Empirical-Bayes shrinkage (fit 2016–2025)

| stat | rho (prior weight) | tau² | σ² per play | mean shrink B | MSE raw L3 | MSE adj L3 | MSE shrunk | MSE league avg |
|---|---|---|---|---|---|---|---|---|
| pass_ypd | 0.182 | 0.2520 | 98.726 | 0.21 | 4.4727 | 4.4377 | 3.3701 | 3.3953 |
| pass_epa | 0.192 | 0.0102 | 2.548 | 0.29 | 0.1222 | 0.1212 | 0.0932 | 0.0938 |
| pass_sr | 0.221 | 0.0009 | 0.247 | 0.27 | 0.0120 | 0.0119 | 0.0093 | 0.0094 |
| rush_ypc | 0.132 | 0.1016 | 39.352 | 0.15 | 2.3520 | 2.3754 | 1.7687 | 1.7776 |
| rush_epa | 0.114 | 0.0029 | 0.982 | 0.16 | 0.0602 | 0.0608 | 0.0451 | 0.0453 |
| rush_sr | 0.185 | 0.0011 | 0.240 | 0.24 | 0.0156 | 0.0157 | 0.0118 | 0.0119 |

## Publishing rule

`lean` requires ≥150 graded backtest bets and a 95% CI lower bound on ROI above -2%. Current: `{"naive_v0|player_pass_yds": false, "naive_v0|player_rush_yds": false, "naive_g10|player_pass_yds": false, "naive_g10|player_rush_yds": false, "l3_v1|player_pass_yds": false, "l3_v1|player_rush_yds": false}`.
