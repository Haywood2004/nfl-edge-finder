export function Impact({ impact }: { impact: string }) {
  const cls = impact === "+" ? "text-up" : impact === "−" || impact === "-" ? "text-down" : "text-flat";
  const glyph = impact === "+" ? "▲" : impact === "−" || impact === "-" ? "▼" : "▬";
  return <span className={`mt-[3px] w-3 shrink-0 text-[10px] ${cls}`} aria-label={impact}>{glyph}</span>;
}
