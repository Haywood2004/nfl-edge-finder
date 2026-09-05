/** Kelly criterion helpers — the single source of truth for stake sizing (site, Kelly page, paper-bet feed).
 *  f* = (p·b − q) / b  where b = decimal odds − 1, q = 1 − p.  Full Kelly maximises log-growth but
 *  assumes p is exactly right; model probabilities are noisy, so fractional Kelly (¼ by default) is used. */
export const DEFAULT_BANKROLL = 100;   // units
export const DEFAULT_FRACTION = 0.25;
export const MIN_STAKE = 0.1;          // units — below this a bet isn't worth logging
export const MAX_STAKE_PCT = 0.03;     // never more than 3% of bankroll on one leg
export const WEEKLY_EXPOSURE_PCT = 0.40; // Kelly sizes each bet against the whole bankroll; with 100+ simultaneous
                                        // bets that sums to several bankrolls, so the week's stakes are scaled down
                                        // proportionally to this budget (2025 backtest: ~180 bets/week unscaled)

/** Scale a week's stakes so their sum does not exceed the exposure budget. Returns the multiplier (≤ 1). */
export function exposureScale(stakes: number[], bankroll = DEFAULT_BANKROLL, exposurePct = WEEKLY_EXPOSURE_PCT): number {
  const total = stakes.reduce((s, x) => s + x, 0);
  const budget = bankroll * exposurePct;
  return total > budget && total > 0 ? budget / total : 1;
}

export function kellyFull(p: number, dec: number): number {
  const b = dec - 1;
  if (b <= 0) return 0;
  return (p * b - (1 - p)) / b;
}

export function kellyStake(p: number, dec: number, bankroll = DEFAULT_BANKROLL, fraction = DEFAULT_FRACTION): number {
  const f = kellyFull(p, dec);
  if (f <= 0) return 0;
  const raw = Math.min(f * fraction, MAX_STAKE_PCT) * bankroll;
  const rounded = Math.round(raw * 20) / 20;   // 0.05-unit steps
  return rounded < MIN_STAKE ? 0 : rounded;
}
