export default function How() {
  return (
    <div className="prose-sm max-w-2xl space-y-4 text-sm leading-relaxed">
      <h1 className="text-xl font-semibold">How it works</h1>
      <p><b>Props.</b> A LightGBM model projects each QB's passing yards from his form, the opponent's pass defense (yards, EPA, pressure — schedule-adjusted), the game script (spread, total, implied points), pace, weather and injuries. It predicts a full distribution, so P(over the line) is a real probability. The projection is blended 35% toward the market line, because the books price things a stats model can't see.</p>
      <p><b>Moneylines.</b> An Elo + EPA ratings model (with rest, divisional, QB changes) predicts win probability, blended 95% toward the sportsbook consensus — that weight was chosen on held-out seasons, and the raw model bet against closing lines loses money at every edge threshold (MODEL.md has the table). Moneyline cards therefore flag <i>price</i> discrepancies between venues — often Polymarket vs the books — rather than model opinions.</p>
      <p><b>Edge</b> = model probability − the implied probability at the best price. <b>Confidence</b> (0–100) starts at ~70 and is reduced for thin samples, new teams, early season, missing injury reports/forecasts, line moves against the pick, and implausibly large edges. A card is flagged at edge ≥ 15% and confidence ≥ 55; everything else is on the Full Board.</p>
      <p><b>Track record.</b> Every flagged pick is graded at the published price after the game. Nothing is deleted.</p>
      <p className="text-muted">Informational only. Not financial advice. 1-800-GAMBLER.</p>
    </div>
  );
}
