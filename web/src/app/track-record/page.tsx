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
    FROM grades g JOIN cards c ON c.id = g.card_id WHERE c.published ORDER BY c.kickoff_utc DESC, c.score DESC LIMIT 500`;
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
