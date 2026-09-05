import { latestCards, latestGameProjections, trackRecord, freshness } from "@/lib/queries";
import { Freshness } from "@/components/Freshness";
import { GameTile, GameLegend } from "@/components/GameTile";
import { Screener } from "@/components/Screener";
import { ago, pct, signedPct } from "@/lib/format";
import { BAR_ML, clearsBar } from "@/lib/thresholds";

export const dynamic = "force-dynamic";

export default async function Home() {
  const [cards, games, rec, f] = await Promise.all([latestCards(), latestGameProjections(), trackRecord(), freshness()]);
  const wk = cards[0] ?? games[0];
  const bets = cards.filter((c) => clearsBar(c.market, Number(c.edge), c.confidence));
  const graded = rec.wins + rec.losses;
  const roi = rec.n ? rec.units / rec.n : 0;

  return (
    <div className="space-y-8">
      <section className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="eyebrow">{wk ? `${wk.season} season · Week ${wk.week}` : "This week"}</p>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight sm:text-3xl">Screener</h1>
          <p className="mt-1 max-w-2xl text-[14px] leading-relaxed text-muted">
            Every prop line the model priced this week. <b className="text-fg">Bets</b> are the ones that clear each market&apos;s bar
            (passing ≥ 6%, receiving &amp; rushing ≥ 8% edge, confidence ≥ 55) — the bars where the closing-line backtests pay. Everything else is visible under &ldquo;Everything priced&rdquo;.
          </p>
          <div className="mt-2"><Freshness /></div>
        </div>
        <div className="grid grid-cols-3 gap-2">
          <Kpi label="Bets" value={String(bets.length)} sub={`of ${cards.length} priced`} tone={bets.length ? "up" : undefined} />
          <Kpi label="Record" value={graded ? `${rec.wins}-${rec.losses}${rec.pushes ? `-${rec.pushes}` : ""}` : "0-0"} sub={graded ? `${pct(rec.wins / graded, 1)} · ${signedPct(roi)} ROI` : "grades after Week 1"} />
          <Kpi label="Model" value={f.trained_at ? ago(f.trained_at) : "–"} sub="last retrain" />
        </div>
      </section>

      <Screener cards={cards} />

      <section>
        <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
          <div>
            <p className="eyebrow">Moneylines</p>
            <h2 className="h-section mt-1">All {games.length} games · win probability</h2>
            <p className="mt-1 text-[13px] text-muted">A moneyline becomes a bet only when a venue pays more than our number implies by {Math.round(BAR_ML * 100)}%+ — those show up in the screener as ML.</p>
          </div>
          <GameLegend />
        </div>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">{games.map((g) => <GameTile key={g.game_id} g={g} />)}</div>
      </section>
    </div>
  );
}

function Kpi({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: "up" | "down" }) {
  return (
    <div className="card kpi min-w-[120px]">
      <div className="kpi-label">{label}</div>
      <div className={`kpi-value ${tone === "up" ? "text-up" : tone === "down" ? "text-down" : ""}`}>{value}</div>
      {sub && <div className="kpi-sub">{sub}</div>}
    </div>
  );
}
