export function Impact({ impact }: { impact: "+" | "−" | "▬" }) {
  const cls = impact === "+" ? "text-up" : impact === "−" ? "text-down" : "text-flat";
  const glyph = impact === "+" ? "▲" : impact === "−" ? "▼" : "▬";
  return <span className={`${cls} w-4 shrink-0 font-mono`}>{glyph}</span>;
}
