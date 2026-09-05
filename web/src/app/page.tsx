import Link from "next/link";
import { latestCards, latestGameProjections, trackRecord, freshness } from "@/lib/queries";
import { Freshness } from "@/components/Freshness";
import { GameTile, GameLegend } from "@/components/GameTile";
import { PropTile } from "@/components/PropTile";
import { EdgeMeter } from "@/components/EdgeMeter";
import { ago, num, pct, signedPct } from "@/lib/format";
import { BAR_PROPS, BAR_ML, barFor, clearsBar } from "@/lib/thresholds";

export const dynamic = "force-dynamic";

export default async function Home() {
  const [cards, games, rec, f] = await Promise.all([latestCards(), latestGameProjections(), trackRecord(), freshness()]);
  const wk = cards[0] ?? games[0];
  const props = cards.filter((c) => c.market !== "h2h");
  const mls = cards.filter((c) => c.market === "h2h");
  const clears = cards.filter((c) => clearsBar(c.market, Number(c.edge), c.confidence));
  // "closest to the bar" ranks by edge × confidence so a 35% edge at confidence 20 (role change the model
  // can't see) doesn't outrank a 9% edge at confidence 56
  const ranked = cards.filter((c) => c.confidence >= 45).sort((a, b) => Number(b.score) - Number(a.score));
  const closest = ranked.slice(0, 4);
  const maxEdge = clears.length ? Math.max(...clears.map((c) => Number(c.edge))) : (closest[0] ? Number(closest[0].edge) : 0);
  const graded = rec.wins + rec.losses;
  const roi = rec.n ? rec.units / rec.n : 0;

  return (
    <div className="space-y-10">
      {/* Hero */}
      <section className="grid gap-6 lg:grid-cols-[1.3fr_1fr] lg:items-end">
        <div>
          <p className="eyebrow">{wk ? `${wk.season} season · Week ${wk.week}` : "This week"}</p>
          <h1 className="mt-2 text-3xl font-semibold leading-[1.1] tracking-tight sm:text-4xl">
            Edges that survive the <span className="bg-gradient-to-r from-accent-2 to-up bg-clip-text text-transparent">matchup check</span>.
          </h1>
          <p className="mt-3 max-w-xl text-[15px] leading-relaxed text-muted">
            Every line on the board is priced against a projection that accounts for the opposing defense, the injury report on both sides and the game environment.
            A prop is flagged when the model&apos;s probability beats the best available price by {Math.round(BAR_PROPS * 100)}–8% or more — each market&apos;s bar is set where its real closing-line backtest pays — and a moneyline only when a venue misprices it by {Math.round(BAR_ML * 100)}%. Every card shows its reasons.
          </p>
          <div className="mt-4"><Freshness /></div>
        </div>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-2">
          <Kpi label="Bets priced" value={String(cards.length)} sub={`${props.length} props · ${mls.length} moneyline`} />
          <Kpi label="Flagged" value={String(clears.length)} sub={`top edge ${signedPct(maxEdge)}`} tone={clears.length ? "up" : undefined} />
          <Kpi label="Record" value={graded ? `${rec.wins}-${rec.losses}${rec.pushes ? `-${rec.pushes}` : ""}` : "0-0"} sub={graded ? `${pct(rec.wins / graded, 1)} · ${signedPct(roi)} ROI` : "grades after Week 1"} />
          <Kpi label="Model" value={f.trained_at ? ago(f.trained_at) : "–"} sub="last retrain" />
        </div>
      </section>

      {/* Flagged */}
      <section className="card p-5 sm:p-6">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <div>
            <p className="eyebrow">Flagged this week</p>
            <h2 className="h-section mt-1">Passing ≥ 6% · receiving &amp; rushing ≥ 8% · moneylines ≥ {Math.round(BAR_ML * 100)}% · confidence ≥ 55</h2>
          </div>
          <Link href="/board" className="text-sm text-accent hover:underline">Full board →</Link>
        </div>
        {clears.length ? (
          <div className="mt-4 grid gap-3 md:grid-cols-2">{clears.map((c) => <PropTile key={c.id} c={c} bar={barFor(c.market)} />)}</div>
        ) : (
          <div className="mt-4 grid gap-5 md:grid-cols-[1fr_1.1fr] md:items-center">
            <div className="min-w-0">
              <p className="text-4xl font-semibold tracking-tight tnum">0 <span className="text-base font-normal text-muted">flagged</span></p>
              <p className="mt-2 text-sm leading-relaxed text-muted">
                The biggest edge on the board is {signedPct(maxEdge)}. Everything below the bar is still priced, explained and tracked as a paper bet.
              </p>
            </div>
            <div className="min-w-0 space-y-1.5">
              <p className="eyebrow mb-2">Closest to the bar</p>
              {closest.map((c) => (
                <Link key={c.id} href={`/cards/${c.id}`} className="flex items-center justify-between gap-4 rounded-lg border border-border/70 bg-panel-2/40 px-3 py-2 text-sm transition-colors hover:border-border-2">
                  <span className="min-w-0 truncate">
                    <span className="font-medium">{c.market === "h2h" ? c.team : c.player_name}</span>
                    <span className="text-muted"> · {c.market === "h2h" ? "ML" : `${c.side} ${c.line ?? ""}`}</span>
                  </span>
                  <EdgeMeter edge={Number(c.edge)} bar={barFor(c.market)} width={90} />
                </Link>
              ))}
            </div>
          </div>
        )}
      </section>

      {/* Games */}
      <section>
        <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
          <div>
            <p className="eyebrow">Moneylines</p>
            <h2 className="h-section mt-1">All {games.length} games · win probability</h2>
          </div>
          <GameLegend />
        </div>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">{games.map((g) => <GameTile key={g.game_id} g={g} />)}</div>
      </section>

      {/* Props */}
      <section>
        <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
          <div>
            <p className="eyebrow">Player props</p>
            <h2 className="h-section mt-1">Passing · receiving · rushing · receptions — best edge × confidence</h2>
          </div>
          <Link href="/board" className="text-sm text-accent hover:underline">All {props.length} priced →</Link>
        </div>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {props.filter((c) => c.confidence >= 45).sort((a, b) => Number(b.score) - Number(a.score)).slice(0, 9).map((c) => <PropTile key={c.id} c={c} bar={barFor(c.market)} />)}
        </div>
      </section>

      {/* Why trust */}
      <section className="grid gap-3 sm:grid-cols-3">
        <Trust title="Matchup-aware, not average-aware" body="Season averages are already in the line. Projections start from the opponent's schedule-adjusted pass defense, pressure rate, injuries and the game script." />
        <Trust title="Calibrated probabilities" body="The model predicts a full distribution, validated on held-out seasons: when it says 60%, it has hit 60%. The model card on the Methodology page shows the numbers." />
        <Trust title="Nothing gets deleted" body={`Every flagged pick is graded at the published price. ${graded ? `${rec.wins}-${rec.losses} so far, ${num(rec.units, 1)}u.` : "The first grades land after Week 1."} Losses stay on the board.`} />
      </section>
    </div>
  );
}

function Kpi({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: "up" | "down" }) {
  return (
    <div className="card kpi">
      <div className="kpi-label">{label}</div>
      <div className={`kpi-value ${tone === "up" ? "text-up" : tone === "down" ? "text-down" : ""}`}>{value}</div>
      {sub && <div className="kpi-sub">{sub}</div>}
    </div>
  );
}

function Trust({ title, body }: { title: string; body: string }) {
  return (
    <div className="card p-4">
      <p className="font-medium">{title}</p>
      <p className="mt-1 text-[13px] leading-relaxed text-muted">{body}</p>
    </div>
  );
}
