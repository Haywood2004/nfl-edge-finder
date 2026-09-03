/** Edge vs the publish bar. Fill = edge (capped at 2× bar); tick = the bar. */
export function EdgeMeter({ edge, bar = 0.15, width = 140 }: { edge: number; bar?: number; width?: number }) {
  const max = bar * 2;
  const pct = Math.max(0, Math.min(1, edge / max));
  const barPct = bar / max;
  const clears = edge >= bar;
  return (
    <div className="flex shrink-0 items-center gap-2" title={`Edge ${(edge * 100).toFixed(1)}% vs ${(bar * 100).toFixed(0)}% bar`}>
      <div className="relative h-2 rounded-full bg-panel-2" style={{ width }}>
        <div className={`absolute inset-y-0 left-0 rounded-full ${clears ? "bg-up" : "bg-accent"}`} style={{ width: `${pct * 100}%` }} />
        <div className="absolute top-[-3px] h-[14px] w-[2px] bg-warn" style={{ left: `${barPct * 100}%` }} />
      </div>
      <span className={`text-sm font-semibold tnum ${clears ? "text-up" : ""}`}>{edge >= 0 ? "+" : ""}{(edge * 100).toFixed(1)}%</span>
    </div>
  );
}
