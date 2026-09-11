import { trackRecord, trackBreakdown } from "@/lib/queries";
import { sql } from "@/lib/db";
import { american, book, MARKET_NAMES, num, pct, signedPct } from "@/lib/format";

export const dynamic = "force-dynamic";
export const metadata = { title: "Track record" };

export default async function TrackRecord() {
  const [t, br] = await Promise.all([trackRecord(), trackBreakdown()]);
  const rows = await sql`
    SELECT c.season, c.week, c.player_name, c.team, c.market, c.side, c.line, c.price_american, c.book, c.edge, c.confidence,
           g.actual, g.result, g.profit_units, g.clv_prob
    FROM grades g JOIN cards c ON c.id = g.card_id WHERE c.published AND c.source = 'model' ORDER BY c.kickoff_utc DESC, c.score DESC LIMIT 500`;
  const mine = await sql`
    SELECT p.placed_at, p.stake_units, p.book, p.price_american, p.line, c.id AS card_id, c.player_name, c.team, c.opponent, c.market, c.side, c.kickoff_utc,
           g.result, g.actual, g.profit_units, g.clv_prob
    FROM placed_bets p JOIN cards c ON c.id = p.card_id LEFT JOIN grades g ON g.card_id = c.id ORDER BY c.kickoff_utc DESC, p.placed_at DESC LIMIT 300`;
  const mineUnits = mine.reduce((s, r) => s + (r.profit_units == null ? 0 : Number(r.profit_units) * Number(r.stake_units)), 0);
  const mineStaked = mine.reduce((s, r) => s + (r.result === "win" || r.result === "loss" ? Number(r.stake_units) : 0), 0);
  const mineW = mine.filter((r) => r.result === "win").length, mineL = mine.filter((r) => r.result === "loss").length, mineP = mine.filter((r) => r.result === "push" || r.result === "void").length;
  const wr = t.wins + t.losses ? t.wins / (t.wins + t.losses) : 0;
  const roi = t.n ? t.units / t.n : 0;
  const kpis: [string, string, string?][] = [
    ["Record", `${t.wins}-${t.losses}-${t.pushes}`, "flagged picks"],
    ["Win rate", pct(wr, 1)],
    ["Units", `${t.units >= 0 ? "+" : ""}${num(t.units, 2)}u`, "1u flat"],
    ["ROI", signedPct(roi), "per unit risked"],
    ["Avg CLV", t.clv == null ? "–" : signedPct(t.clv), "closing-line value"],
  ];
  const groups = [["market", "By market"], ["tier", "By tier"], ["week", "By week"]] as const;
  return (
    <div className="space-y-8">
      <div>
        <p className="eyebrow">Honest ledger</p>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight">Track record</h1>
        <p className="mt-1 max-w-2xl text-sm text-muted">Every flagged pick, graded at the price shown when it was published. Below-bar cards are tracked as paper bets in the breakdown. Nothing is removed.</p>
      </div>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
        {kpis.map(([l, v, s]) => (
          <div key={l} className="card kpi"><div className="kpi-label">{l}</div><div className="kpi-value">{v}</div>{s && <div className="kpi-sub">{s}</div>}</div>
        ))}
      </div>

      {mine.length > 0 && (
        <section className="card p-4 sm:p-5">
          <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="eyebrow">My placed bets</h2>
            <p className="text-sm tnum"><b>{mineW}-{mineL}{mineP ? `-${mineP}` : ""}</b> · staked {mineStaked.toFixed(2)}u · <span className={mineUnits >= 0 ? "text-up" : "text-down"}>{mineUnits >= 0 ? "+" : ""}{mineUnits.toFixed(2)}u</span>{mineStaked > 0 && <span className="text-muted"> ({signedPct(mineUnits / mineStaked)} ROI)</span>}</p>
          </div>
          <div className="overflow-x-auto">
            <table className="data text-[13px]">
              <thead><tr><th>Bet</th><th>Price</th><th>Stake</th><th>Kick</th><th>Actual</th><th>Result</th><th>P&amp;L</th><th>CLV</th></tr></thead>
              <tbody>
                {mine.map((r) => (
                  <tr key={r.card_id}>
                    <td><span className={`pill ${r.side === "Over" ? "pill-up" : "pill-down"}`}>{r.side === "Over" ? "O" : "U"} {Number(r.line)}</span> <span className="font-medium">{r.player_name}</span> <span className="text-muted">{MARKET_NAMES[r.market] ?? r.market} · {r.team} vs {r.opponent}</span></td>
                    <td className="whitespace-nowrap">{american(r.price_american)} <span className="text-muted">{book(r.book)}</span></td>
                    <td>{Number(r.stake_units).toFixed(2)}u</td>
                    <td className="whitespace-nowrap text-muted">{new Date(r.kickoff_utc).toLocaleString("en-US", { timeZone: "America/New_York", weekday: "short", hour: "numeric", minute: "2-digit" })}</td>
                    <td>{r.actual == null ? <span className="text-dim">pending</span> : num(Number(r.actual), 0)}</td>
                    <td className={r.result === "win" ? "text-up" : r.result === "loss" ? "text-down" : "text-muted"}>{r.result ?? "–"}</td>
                    <td className={r.profit_units == null ? "text-dim" : Number(r.profit_units) >= 0 ? "text-up" : "text-down"}>{r.profit_units == null ? "–" : `${Number(r.profit_units) * Number(r.stake_units) >= 0 ? "+" : ""}${(Number(r.profit_units) * Number(r.stake_units)).toFixed(2)}u`}</td>
                    <td className="text-muted">{r.clv_prob == null ? "–" : signedPct(Number(r.clv_prob))}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-[12px] text-muted">Bets you marked as placed in the screener, at the price and stake you took. The pipeline&apos;s own paper record above is systematic and separate.</p>
        </section>
      )}

      {br.length > 0 && (
        <div className="grid gap-3 md:grid-cols-3">
          {groups.map(([kind, title]) => {
            const g = br.filter((r) => r.kind === kind);
            return (
              <section key={kind} className="card overflow-x-auto p-0">
                <table className="data text-[13px]">
                  <thead><tr><th>{title}</th><th>W-L</th><th>Units</th><th>ROI</th><th>CLV</th></tr></thead>
                  <tbody>
                    {g.map((r) => (
                      <tr key={r.key}>
                        <td className="font-medium">{kind === "market" ? MARKET_NAMES[r.key] ?? r.key : kind === "week" ? `Week ${r.key}` : r.key}</td>
                        <td>{r.wins}-{r.losses}{r.pushes ? `-${r.pushes}` : ""}</td>
                        <td className={r.units > 0 ? "text-up" : r.units < 0 ? "text-down" : ""}>{r.units >= 0 ? "+" : ""}{num(r.units, 2)}</td>
                        <td>{r.n ? signedPct(r.units / r.n) : "–"}</td>
                        <td>{r.clv == null ? "–" : signedPct(r.clv)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </section>
            );
          })}
        </div>
      )}

      {rows.length === 0 ? (
        <div className="card p-10 text-center">
          <p className="text-lg font-medium">No graded picks yet</p>
          <p className="mt-1 text-sm text-muted">Grades land automatically the morning after each week&apos;s games finalize. Until then, every priced bet is locked as a paper bet at the price shown when it was first flagged.</p>
        </div>
      ) : (
        <div className="card overflow-x-auto p-0">
          <table className="data text-[13px]">
            <thead><tr>{["Week", "Pick", "Market", "Price", "Edge", "Conf", "Actual", "Result", "Units", "CLV"].map((h) => <th key={h}>{h}</th>)}</tr></thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i}>
                  <td className="text-muted">{r.season} W{r.week}</td>
                  <td><span className="font-medium">{r.market === "h2h" ? r.team : r.player_name}</span> <span className="text-muted">{r.market === "h2h" ? "to win" : `${r.side} ${r.line}`}</span></td>
                  <td className="text-muted">{MARKET_NAMES[r.market] ?? r.market}</td>
                  <td>{american(r.price_american)} <span className="text-muted">{book(r.book)}</span></td>
                  <td>{signedPct(Number(r.edge))}</td><td>{r.confidence}</td><td>{r.actual ?? "–"}</td>
                  <td><span className={`pill ${r.result === "win" ? "pill-up" : r.result === "loss" ? "pill-down" : ""}`}>{r.result}</span></td>
                  <td className={Number(r.profit_units) > 0 ? "text-up" : Number(r.profit_units) < 0 ? "text-down" : ""}>{num(r.profit_units, 2)}</td>
                  <td>{r.clv_prob == null ? "–" : signedPct(Number(r.clv_prob))}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
