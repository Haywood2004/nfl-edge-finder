import Link from "next/link";
import { notFound } from "next/navigation";
import { latestGameProjections, gameCards } from "@/lib/queries";
import { american, book, kickoff, TEAM_NAMES, pct } from "@/lib/format";
import { FactorList } from "@/components/FactorList";
import { EdgeMeter } from "@/components/EdgeMeter";
import { GameLegend } from "@/components/GameTile";

export const dynamic = "force-dynamic";

export default async function GamePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const games = await latestGameProjections();
  const g = games.find((x) => x.game_id === id);
  if (!g) notFound();
  const cards = await gameCards(id);
  const rows: [string, number | null, string][] = [
    ["Our number (bettable)", Number(g.p_home_used), "bg-cmodel"],
    ["Sportsbooks (no-vig)", g.p_home_market == null ? null : Number(g.p_home_market), "bg-cbooks"],
    ["Polymarket", g.p_home_polymarket == null ? null : Number(g.p_home_polymarket), "bg-cpoly"],
    ["Ratings model alone (diagnostic — loses vs closing lines, not bettable)", Number(g.p_home_model), "bg-dim"],
  ];
  return (
    <div className="space-y-6">
      <div>
        <Link href="/" className="text-xs text-muted hover:underline">← This week</Link>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight">{TEAM_NAMES[g.away_team]} @ {TEAM_NAMES[g.home_team]}</h1>
        <p className="text-sm text-muted">{kickoff(g.kickoff_utc)} · Elo {g.away_team} {Number(g.elo_away).toFixed(0)} · {g.home_team} {Number(g.elo_home).toFixed(0)}</p>
      </div>
      <section className="card p-4 sm:p-5">
        <h2 className="eyebrow mb-3">Home win probability · {TEAM_NAMES[g.home_team]}</h2>
        <div className="space-y-2">
          {rows.map(([label, p, cls]) => (
            <div key={label} className="grid grid-cols-[1fr_56px] sm:grid-cols-[260px_1fr_56px] items-center gap-3 text-sm">
              <span className="text-muted">{label}</span>
              <div className="relative h-3 rounded-full bg-panel-2">
                {p != null && <div className={`absolute inset-y-0 left-0 rounded-full ${cls}`} style={{ width: `${p * 100}%` }} />}
                <div className="absolute top-[-2px] left-1/2 h-4 w-[1px] bg-muted/50" />
              </div>
              <span className="text-right tnum">{p == null ? "–" : pct(p, 1)}</span>
            </div>
          ))}
        </div>
        <div className="mt-3"><GameLegend /></div>
      </section>
      <section className="card p-4 sm:p-5">
        <h2 className="eyebrow mb-2">Why</h2>
        <FactorList factors={g.factors.map((f) => ({ ...f, impact: (f as { impact?: "+" | "−" | "▬" }).impact ?? "▬" }))} season={g.season} week={g.week} />
      </section>
      <section className="card p-4 sm:p-5">
        <h2 className="eyebrow mb-2">Moneyline prices vs the blend</h2>
        {cards.length === 0 ? <p className="text-sm text-muted">No venue is priced better than the blended probability right now.</p> : (
          <div className="space-y-2">
            {cards.map((c) => (
              <div key={c.id} className="flex flex-wrap items-center justify-between gap-2 text-sm">
                <span>{TEAM_NAMES[c.side]} <span className="text-muted tnum">{american(c.price_american)} {book(c.book)}</span> · model {pct(Number(c.model_prob), 1)} vs implied {pct(Number(c.market_prob), 1)}</span>
                <EdgeMeter edge={Number(c.edge)} />
              </div>
            ))}
          </div>
        )}
        <p className="mt-2 text-xs text-muted">Moneyline cards flag venues priced better than the sharp consensus. A raw ratings model bet against closing lines loses (see MODEL.md), so the model is blended 95% toward the market.</p>
      </section>
    </div>
  );
}
