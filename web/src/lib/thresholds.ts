/** Publish bars — mirror pipeline/nfl_edge/config.py (DECISIONS.md #24). */
export const BAR_PROPS = 0.06;   // real closing-line backtest 2023–25: ≥6% → 446 bets, 55.6%, +6.5% ROI
export const BAR_ML = 0.15;      // moneyline cards are venue price gaps; the user's 15% bar stays
export const MIN_CONF = 55;
export const BAR_BY_MARKET: Record<string, number> = {
  player_pass_yds: 0.06, player_reception_yds: 0.08, player_receptions: 0.08, player_rush_yds: 0.08, h2h: BAR_ML,
};
export const barFor = (market: string) => BAR_BY_MARKET[market] ?? BAR_PROPS;
export const clearsBar = (market: string, edge: number, confidence: number) => edge >= barFor(market) && confidence >= MIN_CONF;
