/** Normal projection density with the line marked. Pure SVG, no library. */
export function DistChart({ mean, sd, line, side }: { mean: number; sd: number; line: number; side: string }) {
  const W = 560, H = 160, padL = 8, padB = 22;
  const x0 = mean - 3.2 * sd, x1 = mean + 3.2 * sd;
  const xs = (x: number) => padL + ((x - x0) / (x1 - x0)) * (W - 2 * padL);
  const pdf = (x: number) => Math.exp(-0.5 * ((x - mean) / sd) ** 2);
  const n = 120;
  const pts = Array.from({ length: n + 1 }, (_, i) => x0 + ((x1 - x0) * i) / n);
  const ys = (x: number) => H - padB - pdf(x) * (H - padB - 12);
  const path = pts.map((x, i) => `${i ? "L" : "M"}${xs(x).toFixed(1)},${ys(x).toFixed(1)}`).join(" ");
  const shade = pts.filter((x) => (side === "Over" ? x > line : x < line));
  const shadePath = shade.length
    ? `M${xs(shade[0]).toFixed(1)},${H - padB} ` + shade.map((x) => `L${xs(x).toFixed(1)},${ys(x).toFixed(1)}`).join(" ") + ` L${xs(shade[shade.length - 1]).toFixed(1)},${H - padB} Z`
    : "";
  const ticks = [-2, -1, 0, 1, 2].map((k) => mean + k * sd);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="Projection distribution">
      <path d={shadePath} fill={side === "Over" ? "var(--up)" : "var(--down)"} opacity="0.25" />
      <path d={path} fill="none" stroke="var(--accent)" strokeWidth="2" />
      <line x1={xs(line)} x2={xs(line)} y1={8} y2={H - padB} stroke="var(--warn)" strokeWidth="1.5" strokeDasharray="4 3" />
      <text x={xs(line) + 4} y={16} fill="var(--warn)" fontSize="11">line {line}</text>
      <line x1={xs(mean)} x2={xs(mean)} y1={ys(mean)} y2={H - padB} stroke="var(--muted)" strokeWidth="1" />
      <text x={xs(mean) - 4} y={16} fill="var(--muted)" fontSize="11" textAnchor="end">proj {mean.toFixed(0)}</text>
      {ticks.map((t) => (
        <text key={t} x={xs(t)} y={H - 6} fill="var(--muted)" fontSize="10" textAnchor="middle">{t.toFixed(0)}</text>
      ))}
    </svg>
  );
}
