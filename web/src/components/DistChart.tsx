/** Projection density with the line marked. Pure SVG, no library.
 *  When quantiles are given the curve is the model's (skewed) distribution — the CDF is a monotone cubic through
 *  P10/P25/P50/P75/P90 and the density is its derivative — so the shaded area IS the model probability.
 *  Falls back to a normal(mean, sd) when quantiles are missing. */
export type Quantiles = { q10: number; q25: number; q50: number; q75: number; q90: number };

function pchip(xs: number[], ys: number[]) {
  const n = xs.length, h: number[] = [], d: number[] = [];
  for (let i = 0; i < n - 1; i++) { h.push(xs[i + 1] - xs[i]); d.push((ys[i + 1] - ys[i]) / h[i]); }
  const m: number[] = new Array(n).fill(0);
  m[0] = d[0]; m[n - 1] = d[n - 2];
  for (let i = 1; i < n - 1; i++) m[i] = d[i - 1] * d[i] <= 0 ? 0 : (2 * d[i - 1] * d[i]) / (d[i - 1] + d[i]);
  return (x: number) => {
    if (x <= xs[0]) return ys[0];
    if (x >= xs[n - 1]) return ys[n - 1];
    let i = 0; while (x > xs[i + 1]) i++;
    const t = (x - xs[i]) / h[i], t2 = t * t, t3 = t2 * t;
    return (2 * t3 - 3 * t2 + 1) * ys[i] + (t3 - 2 * t2 + t) * h[i] * m[i] + (-2 * t3 + 3 * t2) * ys[i + 1] + (t3 - t2) * h[i] * m[i + 1];
  };
}

export function DistChart({ mean, sd, line, side, q, floorZero }: { mean: number; sd: number; line: number; side: string; q?: Quantiles; floorZero?: boolean }) {
  const W = 560, H = 160, padL = 8, padB = 22;
  let x0: number, x1: number, pdf: (x: number) => number, marker: number, markerLabel: string;
  if (q && [q.q10, q.q25, q.q50, q.q75, q.q90].every((v) => Number.isFinite(v)) && q.q10 < q.q25 && q.q25 < q.q50 && q.q50 < q.q75 && q.q75 < q.q90) {
    const lo = q.q10 - 1.6 * (q.q25 - q.q10), hi = q.q90 + 1.6 * (q.q90 - q.q75);
    const left = floorZero ? Math.max(lo, 0) : lo;
    const xs = [left, q.q10, q.q25, q.q50, q.q75, q.q90, hi], ps = [left === 0 && lo < 0 ? 0.02 : 0.005, 0.1, 0.25, 0.5, 0.75, 0.9, 0.995];
    const cdf = pchip(xs, ps);
    const eps = (hi - left) / 400;
    pdf = (x: number) => Math.max((cdf(x + eps) - cdf(x - eps)) / (2 * eps), 0);
    x0 = left; x1 = hi; marker = q.q50; markerLabel = `median ${q.q50.toFixed(0)}`;
  } else {
    x0 = mean - 3.2 * sd; x1 = mean + 3.2 * sd;
    pdf = (x: number) => Math.exp(-0.5 * ((x - mean) / sd) ** 2);
    marker = mean; markerLabel = `proj ${mean.toFixed(0)}`;
  }
  x0 = Math.min(x0, line - 0.05 * (x1 - x0)); x1 = Math.max(x1, line + 0.05 * (x1 - x0));
  const xs = (x: number) => padL + ((x - x0) / (x1 - x0)) * (W - 2 * padL);
  const n = 160;
  const pts = Array.from({ length: n + 1 }, (_, i) => x0 + ((x1 - x0) * i) / n);
  const peak = Math.max(...pts.map(pdf), 1e-9);
  const ys = (x: number) => H - padB - (pdf(x) / peak) * (H - padB - 12);
  const path = pts.map((x, i) => `${i ? "L" : "M"}${xs(x).toFixed(1)},${ys(x).toFixed(1)}`).join(" ");
  const shade = pts.filter((x) => (side === "Over" ? x > line : x < line));
  const shadePath = shade.length
    ? `M${xs(shade[0]).toFixed(1)},${H - padB} ` + shade.map((x) => `L${xs(x).toFixed(1)},${ys(x).toFixed(1)}`).join(" ") + ` L${xs(shade[shade.length - 1]).toFixed(1)},${H - padB} Z`
    : "";
  const step = niceStep((x1 - x0) / 5);
  const ticks: number[] = [];
  for (let t = Math.ceil(x0 / step) * step; t <= x1; t += step) ticks.push(t);
  const labelLeft = marker <= line;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="Projection distribution">
      <path d={shadePath} fill={side === "Over" ? "var(--up)" : "var(--down)"} opacity="0.25" />
      <path d={path} fill="none" stroke="var(--accent)" strokeWidth="2" />
      <line x1={xs(line)} x2={xs(line)} y1={8} y2={H - padB} stroke="var(--warn)" strokeWidth="1.5" strokeDasharray="4 3" />
      <text x={xs(line) + (labelLeft ? 4 : -4)} y={16} fill="var(--warn)" fontSize="11" textAnchor={labelLeft ? "start" : "end"}>line {line}</text>
      <line x1={xs(marker)} x2={xs(marker)} y1={ys(marker)} y2={H - padB} stroke="var(--muted)" strokeWidth="1" />
      <text x={xs(marker) + (labelLeft ? -4 : 4)} y={16} fill="var(--muted)" fontSize="11" textAnchor={labelLeft ? "end" : "start"}>{markerLabel}</text>
      {ticks.map((t) => (
        <text key={t} x={xs(t)} y={H - 6} fill="var(--muted)" fontSize="10" textAnchor="middle">{t.toFixed(0)}</text>
      ))}
    </svg>
  );
}

function niceStep(raw: number) {
  const p = Math.pow(10, Math.floor(Math.log10(raw)));
  const r = raw / p;
  return (r < 1.5 ? 1 : r < 3.5 ? 2.5 : r < 7.5 ? 5 : 10) * p;
}
