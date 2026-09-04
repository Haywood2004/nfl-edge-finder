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
  const fav = used >= 0.5 ? g.home_team : g.away_team;
  return (
    <Link href={`/games/${g.game_id}`} className="card card-hover block min-w-0 overflow-hidden p-4">
      <div className="flex items-baseline justify-between">
        <span className="text-[15px] font-semibold tracking-tight">{g.away_team} <span className="font-normal text-dim">@</span> {g.home_team}</span>
        <span className="text-[12px] text-muted">{kickoff(g.kickoff_utc)}</span>
      </div>
      <div className="mt-3 flex items-baseline justify-between text-[12px]">
        <span className={fav === g.away_team ? "font-medium text-fg" : "text-muted"}>{TEAM_NAMES[g.away_team]} <span className="tnum">{Math.round((1 - used) * 100)}%</span></span>
        <span className={fav === g.home_team ? "font-medium text-fg" : "text-muted"}><span className="tnum">{Math.round(used * 100)}%</span> {TEAM_NAMES[g.home_team]}</span>
      </div>
      <div className="relative mt-1.5 h-2.5 rounded-full bg-panel-3">
        <div className="absolute inset-y-0 left-0 rounded-l-full bg-cmodel/30" style={{ width: `${used * 100}%` }} />
        <Marker p={pm} cls="bg-cmodel" title={`Model ${(pm * 100).toFixed(0)}%`} />
        {pb != null && <Marker p={pb} cls="bg-cbooks" title={`Books ${(pb * 100).toFixed(0)}%`} />}
        {pp != null && <Marker p={pp} cls="bg-cpoly" title={`Polymarket ${(pp * 100).toFixed(0)}%`} />}
        <div className="absolute top-[-3px] left-1/2 h-4 w-[1px] bg-muted/40" />
      </div>
      <div className="mt-2 flex items-center justify-between text-[12px] tnum text-muted">
        <span>{g.away_best ? <><span className="text-fg-2">{american(g.away_best.american)}</span> {book(g.away_best.book)}</> : "–"}</span>
        <span>{g.home_best ? <><span className="text-fg-2">{american(g.home_best.american)}</span> {book(g.home_best.book)}</> : "–"}</span>
      </div>
      {(disagree >= 0.08 || (polyGap != null && Math.abs(polyGap) >= 0.02)) && (
        <div className="mt-2.5 flex flex-wrap gap-1">
          {disagree >= 0.08 && <span className="pill pill-warn">model ≠ market by {Math.round(disagree * 100)} pts</span>}
          {polyGap != null && Math.abs(polyGap) >= 0.02 && <span className="pill" style={{ color: "var(--c-poly)", borderColor: "color-mix(in srgb, var(--c-poly) 35%, transparent)", background: "color-mix(in srgb, var(--c-poly) 12%, transparent)" }}>Polymarket {polyGap > 0 ? "+" : ""}{Math.round(polyGap * 100)} pts on {polyGap > 0 ? g.home_team : g.away_team}</span>}
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
    <div className="flex flex-wrap gap-x-4 gap-y-1 text-[12px] text-muted">
      <span className="flex items-center gap-1.5"><i className="inline-block h-2.5 w-2.5 rounded-full bg-cmodel" /> Ratings model</span>
      <span className="flex items-center gap-1.5"><i className="inline-block h-2.5 w-2.5 rounded-full bg-cbooks" /> Sportsbooks (no-vig)</span>
      <span className="flex items-center gap-1.5"><i className="inline-block h-2.5 w-2.5 rounded-full bg-cpoly" /> Polymarket</span>
      <span className="text-dim">Bar = blended home win probability · centre = 50%</span>
    </div>
  );
}
