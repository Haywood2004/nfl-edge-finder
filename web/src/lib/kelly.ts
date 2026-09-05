/** Kelly criterion helpers — the single source of truth for stake sizing (site, Kelly page, paper-bet feed).
 *  f* = (p·b − q) / b  where b = decimal odds − 1, q = 1 − p.  Full Kelly maximises log-growth but
 *  assumes p is exactly right; model probabilities are noisy, so fractional Kelly (¼ by default) is used. */
export const DEFAULT_BANKROLL = 100;   // units
export const DEFAULT_FRACTION = 0.25;
export const MIN_STAKE = 0.1;          // units — below this a bet isn't worth logging
export const MAX_STAKE_PCT = 0.03;     // never more than 3% of bankroll on one leg

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
