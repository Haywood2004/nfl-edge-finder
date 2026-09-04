/** Publish bars — mirror pipeline/nfl_edge/config.py (DECISIONS.md #24). */
export const BAR_PROPS = 0.06;   // real closing-line backtest 2023–25: ≥6% → 446 bets, 55.6%, +6.5% ROI
export const BAR_ML = 0.15;      // moneyline cards are venue price gaps; the user's 15% bar stays
export const MIN_CONF = 55;
export const barFor = (market: string) => (market === "h2h" ? BAR_ML : BAR_PROPS);
export const clearsBar = (market: string, edge: number, confidence: number) => edge >= barFor(market) && confidence >= MIN_CONF;
