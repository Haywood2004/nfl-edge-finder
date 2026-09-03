import Link from "next/link";
import type { GameProjection } from "@/lib/queries";
import { american, book, kickoff, TEAM_NAMES } from "@/lib/format";

/** One game: a 0–100 track of HOME win probability with markers for model / books / Polymarket. */
export function GameTile({ g }: { g: GameProjection }) {
  const pm = Number(g.p_home_model), pb = g.p_home_market == null ? null : Number(g.p_home_market);
  const pp = g.p_home_polymarket == null ? null : Number(g.p_home_polymarket);
  const used = Number(g.p_home_used);
  const disagree = pb != null ? Math.abs(pm - pb) : 0;
  const polyGap = pb != null && pp != null ? pp - pb : null;
  return (
    <Link href={`/games/${g.game_id}`} className="block rounded-lg border border-border bg-panel p-3 hover:border-accent/60">
      <div className="flex items-baseline justify-between text-sm">
        <span className="font-semibold">{g.away_team} <span className="text-muted">@</span> {g.home_team}</span>
        <span className="text-xs text-muted">{kickoff(g.kickoff_utc)}</span>
      </div>
      <div className="mt-2 flex items-center justify-between text-xs text-muted">
        <span>{TEAM_NAMES[g.away_team]} {Math.round((1 - used) * 100)}%</span>
        <span>{Math.round(used * 100)}% {TEAM_NAMES[g.home_team]}</span>
      </div>
      <div className="relative mt-1 h-3 rounded-full bg-panel-2">
        <div className="absolute inset-y-0 left-0 rounded-l-full bg-cmodel/25" style={{ width: `${used * 100}%` }} />
        <div className="absolute top-1/2 h-[1px] w-full bg-border" />
        <Marker p={pm} cls="bg-cmodel" title={`Model ${(pm * 100).toFixed(0)}%`} />
        {pb != null && <Marker p={pb} cls="bg-cbooks" title={`Books ${(pb * 100).toFixed(0)}%`} />}
        {pp != null && <Marker p={pp} cls="bg-cpoly" title={`Polymarket ${(pp * 100).toFixed(0)}%`} />}
        <div className="absolute top-[-2px] left-1/2 h-4 w-[1px] bg-muted/50" />
      </div>
      <div className="mt-2 flex items-center justify-between text-xs tnum">
        <span className="text-muted">{g.away_best ? `${american(g.away_best.american)} ${book(g.away_best.book)}` : "–"}</span>
        <span className="text-muted">{g.home_best ? `${american(g.home_best.american)} ${book(g.home_best.book)}` : "–"}</span>
      </div>
      {(disagree >= 0.08 || (polyGap != null && Math.abs(polyGap) >= 0.02)) && (
        <div className="mt-1.5 flex flex-wrap gap-1">
          {disagree >= 0.08 && <span className="rounded bg-warn/15 px-1.5 py-0.5 text-[11px] text-warn">model ≠ market by {Math.round(disagree * 100)} pts</span>}
          {polyGap != null && Math.abs(polyGap) >= 0.02 && <span className="rounded bg-cpoly/15 px-1.5 py-0.5 text-[11px] text-cpoly">Polymarket {polyGap > 0 ? "+" : ""}{Math.round(polyGap * 100)} pts on {polyGap > 0 ? g.home_team : g.away_team}</span>}
        </div>
      )}
    </Link>
  );
}

function Marker({ p, cls, title }: { p: number; cls: string; title: string }) {
  return <div className={`absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full ring-2 ring-panel ${cls}`} style={{ left: `${p * 100}%` }} title={title} />;
}

export function GameLegend() {
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
      <span className="flex items-center gap-1.5"><i className="inline-block h-2.5 w-2.5 rounded-full bg-cmodel" /> Ratings model</span>
      <span className="flex items-center gap-1.5"><i className="inline-block h-2.5 w-2.5 rounded-full bg-cbooks" /> Sportsbooks (no-vig)</span>
      <span className="flex items-center gap-1.5"><i className="inline-block h-2.5 w-2.5 rounded-full bg-cpoly" /> Polymarket</span>
      <span>Bar = blended win probability for the home team · centre line = 50%</span>
    </div>
  );
}
