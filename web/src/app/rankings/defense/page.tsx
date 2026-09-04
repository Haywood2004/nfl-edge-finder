import { defenseTable } from "@/lib/queries";
import { sql } from "@/lib/db";
import { TEAM_NAMES, num } from "@/lib/format";

export const dynamic = "force-dynamic";

const COLS: [string, string, string][] = [
  ["pass_yds_allowed_pg", "pass_yds_allowed_rank", "Pass yds/g"],
  ["sos_adj_pass_yds_allowed", "sos_adj_pass_rank", "SOS-adj pass yds/g"],
  ["pass_epa_allowed", "pass_epa_allowed_rank", "EPA/dropback"],
  ["yds_per_dropback_allowed", "yds_per_dropback_rank", "Yds/dropback"],
  ["wr_yds_allowed_pg", "wr_yds_allowed_rank", "WR yds/g"],
  ["te_yds_allowed_pg", "te_yds_allowed_rank", "TE yds/g"],
  ["rb_rec_yds_allowed_pg", "rb_rec_yds_allowed_rank", "RB rec yds/g"],
  ["rush_yds_allowed_pg", "rush_yds_allowed_rank", "Rush yds/g"],
];

export default async function DefensePage({ searchParams }: { searchParams: Promise<Record<string, string | undefined>> }) {
  const sp = await searchParams;
  const [latest] = await sql`SELECT season, week FROM feat_team_defense ORDER BY season DESC, week DESC LIMIT 1`;
  const season = Number(sp.season ?? latest?.season), week = Number(sp.week ?? latest?.week);
  const rows = await defenseTable(season, week);
  const hl = sp.team;
  return (
    <div>
      <p className="eyebrow">Rankings</p>
      <h1 className="mt-1 text-2xl font-semibold tracking-tight">Pass defense · {season} Week {week}</h1>
      <p className="mb-3 text-sm text-muted">
        Point-in-time: built from games before Week {week}{rows[0] && Number(rows[0].games) === 0 ? " — no current-season games yet, so this is last season shrunk 50% toward league average" : ""}.
        Rank 1 = fewest allowed. Derived from nflverse play-by-play; sacks excluded from passing yards (gross), matching public tables.
      </p>
      <div className="card overflow-x-auto">
        <table className="data text-sm">
          <thead>
            <tr><th>Team</th><th>G</th>{COLS.map(([, r, l]) => <th key={r} id={r}>{l}</th>)}<th>Sack%</th></tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.team} className={r.team === hl ? "bg-accent/10" : ""}>
                <td><span className="font-medium">{r.team}</span> <span className="text-muted">{TEAM_NAMES[r.team]}</span></td>
                <td>{r.games}</td>
                {COLS.map(([v, rk]) => (
                  <td key={v}>{num(r[v], v.includes("epa") || v.includes("dropback") ? 2 : 1)} <span className="text-xs text-muted">#{r[rk]}</span></td>
                ))}
                <td>{num(Number(r.sack_rate) * 100, 1)}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
