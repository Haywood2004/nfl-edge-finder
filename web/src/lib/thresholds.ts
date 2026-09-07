/** Publish bars — mirror pipeline/nfl_edge/config.py (DECISIONS.md #24). */
export const BAR_PROPS = 0.06;   // real closing-line backtest 2023–25: ≥6% → 446 bets, 55.6%, +6.5% ROI
export const BAR_ML = 0.15;      // moneyline cards are venue price gaps; the user's 15% bar stays
export const MIN_CONF = 55;
export const BAR_BY_MARKET: Record<string, number> = {
  // DK/FD-only closing-line backtest (DECISIONS.md #37)
  player_pass_yds: 0.08, player_reception_yds: 0.10, player_receptions: 0.15, player_rush_yds: 0.06, h2h: BAR_ML,
};
/** Human summary of the bars, e.g. "passing 8%, rec yds 10%, receptions 15%, rushing 6%". */
export const BARS_TEXT = `passing ${Math.round(BAR_BY_MARKET.player_pass_yds * 100)}%, rec yds ${Math.round(BAR_BY_MARKET.player_reception_yds * 100)}%, receptions ${Math.round(BAR_BY_MARKET.player_receptions * 100)}%, rushing ${Math.round(BAR_BY_MARKET.player_rush_yds * 100)}%`;
export const VENUES_TEXT = "DraftKings, FanDuel, Pinnacle";
export const barFor = (market: string) => BAR_BY_MARKET[market] ?? BAR_PROPS;
export const clearsBar = (market: string, edge: number, confidence: number) => edge >= barFor(market) && confidence >= MIN_CONF;
