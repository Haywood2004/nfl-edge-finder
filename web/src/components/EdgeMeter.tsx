/** Edge vs the publish bar. Fill = edge (capped at 2× bar); tick = the bar. width 999 = fill the row. */
export function EdgeMeter({ edge, bar = 0.15, width = 140 }: { edge: number; bar?: number; width?: number }) {
  const max = bar * 2;
  const pct = Math.max(0, Math.min(1, edge / max));
  const barPct = bar / max;
  const clears = edge >= bar;
  const fluid = width >= 999;
  return (
    <div className={`flex items-center gap-2.5 ${fluid ? "w-full" : "shrink-0"}`} title={`Edge ${(edge * 100).toFixed(1)}% vs ${(bar * 100).toFixed(0)}% bar`}>
      <div className={`relative h-1.5 rounded-full bg-panel-3 ${fluid ? "flex-1" : ""}`} style={fluid ? undefined : { width }}>
        <div className={`absolute inset-y-0 left-0 rounded-full ${clears ? "bg-up" : "bg-accent"}`} style={{ width: `${pct * 100}%` }} />
        <div className="absolute top-[-4px] h-[14px] w-[2px] rounded bg-warn/90" style={{ left: `${barPct * 100}%` }} />
      </div>
      <span className={`w-14 text-right text-[13px] font-semibold tnum ${clears ? "text-up" : "text-fg"}`}>{edge >= 0 ? "+" : ""}{(edge * 100).toFixed(1)}%</span>
    </div>
  );
}
