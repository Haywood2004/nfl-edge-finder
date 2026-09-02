import { trackRecord } from "@/lib/queries";
import { sql } from "@/lib/db";
import { american, book, MARKET_NAMES, num, pct, signedPct } from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function TrackRecord() {
  const t = await trackRecord();
  const rows = await sql`
    SELECT c.season, c.week, c.player_name, c.market, c.side, c.line, c.price_american, c.book, c.edge, c.confidence,
           g.actual, g.result, g.profit_units, g.clv_prob
    FROM grades g JOIN cards c ON c.id = g.card_id WHERE c.published ORDER BY c.kickoff_utc DESC, c.score DESC LIMIT 500`;
  const wr = t.wins + t.losses ? t.wins / (t.wins + t.losses) : 0;
  const roi = t.n ? t.units / t.n : 0;
  return (
    <div>
      <h1 className="text-xl font-semibold">Track record</h1>
      <p className="mb-4 text-sm text-muted">Every published pick, graded at the price shown when it was published. Nothing is removed.</p>
      <div className="mb-5 grid grid-cols-2 gap-2 text-center text-sm tnum sm:grid-cols-5">
        {[["Record", `${t.wins}-${t.losses}-${t.pushes}`], ["Win rate", pct(wr, 1)], ["Units", `${t.units >= 0 ? "+" : ""}${num(t.units, 2)}u`],
          ["ROI", signedPct(roi)], ["Avg CLV", t.clv == null ? "–" : signedPct(t.clv)]].map(([l, v]) => (
          <div key={l} className="rounded border border-border bg-panel px-2 py-2"><div className="text-[11px] uppercase text-muted">{l}</div><div className="font-semibold">{v}</div></div>
        ))}
      </div>
      {rows.length === 0 ? (
        <p className="rounded-lg border border-border bg-panel p-6 text-center text-sm text-muted">No graded picks yet — the first grades land after Week 1 finalizes.</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-sm tnum">
            <thead className="bg-panel text-left text-xs text-muted"><tr>{["Wk", "Player", "Market", "Pick", "Price", "Edge", "Conf", "Actual", "Result", "Units", "CLV"].map((h) => <th key={h} className="px-2 py-2">{h}</th>)}</tr></thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i} className="border-t border-border/60">
                  <td className="px-2 py-1">{r.season} W{r.week}</td><td className="px-2">{r.player_name}</td><td className="px-2">{MARKET_NAMES[r.market] ?? r.market}</td>
                  <td className="px-2">{r.side} {r.line}</td><td className="px-2">{american(r.price_american)} {book(r.book)}</td>
                  <td className="px-2">{signedPct(Number(r.edge))}</td><td className="px-2">{r.confidence}</td><td className="px-2">{r.actual}</td>
                  <td className={`px-2 ${r.result === "win" ? "text-up" : r.result === "loss" ? "text-down" : ""}`}>{r.result}</td>
                  <td className="px-2">{num(r.profit_units, 2)}</td><td className="px-2">{r.clv_prob == null ? "–" : signedPct(Number(r.clv_prob))}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
