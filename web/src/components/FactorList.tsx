import Link from "next/link";
import type { Factor } from "@/lib/queries";
import { Impact } from "./Impact";

function sourceHref(f: Factor, season: number, week: number): string | null {
  const s = f.source;
  if (!s) return null;
  if (s.table === "feat_team_defense") return `/rankings/defense?season=${season}&week=${week}&team=${s.team ?? ""}#${s.key ?? ""}`;
  return null;
}

export function FactorList({ factors, season, week, limit }: { factors: Factor[]; season: number; week: number; limit?: number }) {
  const list = limit ? factors.slice(0, limit) : factors;
  return (
    <ul className="space-y-1.5 text-sm">
      {list.map((f, i) => {
        const href = sourceHref(f, season, week);
        return (
          <li key={i} className="flex gap-2 leading-snug">
            <Impact impact={f.impact} />
            <span className="text-fg/90">
              {f.text}
              {href && (
                <Link href={href} className="ml-1.5 text-xs text-accent hover:underline">table ↗</Link>
              )}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
