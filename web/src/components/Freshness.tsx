import { freshness } from "@/lib/queries";
import { ago } from "@/lib/format";

export async function Freshness() {
  const f = await freshness();
  const item = (label: string, ts: string | null) => (
    <span><span className="text-muted">{label}</span> {ts ? ago(ts) : "never"}</span>
  );
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
      {item("Lines fetched", f.odds_at)} {item("Model scored", f.scored_at)} {item("Model trained", f.trained_at)}
      {item("Injuries updated", f.injuries_at)} {item("Stats ingested", f.ingested_at)}
    </div>
  );
}
