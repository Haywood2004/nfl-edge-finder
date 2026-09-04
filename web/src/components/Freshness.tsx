import { freshness } from "@/lib/queries";
import { ago } from "@/lib/format";

export async function Freshness() {
  const f = await freshness();
  const item = (label: string, ts: string | null) => (
    <span className="whitespace-nowrap"><span className="text-dim">{label}</span> <span className="text-fg-2">{ts ? ago(ts) : "never"}</span></span>
  );
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 text-[12px]">
      {item("Lines", f.odds_at)} {item("Scored", f.scored_at)} {item("Trained", f.trained_at)}
      {item("Injuries", f.injuries_at)} {item("Stats", f.ingested_at)}
    </div>
  );
}

/** Header pill: a live dot plus when lines were last fetched. Fails soft if the DB is unreachable. */
export async function StatusPill() {
  try {
    const f = await freshness();
    const fresh = f.odds_at && Date.now() - +new Date(f.odds_at) < 36 * 3600 * 1000;
    return (
      <span className="pill" title="When sportsbook lines were last fetched">
        <i className={`inline-block h-1.5 w-1.5 rounded-full ${fresh ? "bg-up" : "bg-warn"}`} />
        <span className="hidden sm:inline">Lines</span> {f.odds_at ? ago(f.odds_at) : "–"}
      </span>
    );
  } catch {
    return null;
  }
}
