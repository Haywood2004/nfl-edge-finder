import { sql } from "@/lib/db";
import { ago } from "@/lib/format";

export const dynamic = "force-dynamic";
export const metadata = { title: "Master agent reports", robots: { index: false, follow: false } };

type Row = { id: number; created_at: string; task: string; status: string; cost_usd: string | null; turns: number | null; report: string };

/** Reports written by agents/master.py (members-only via proxy.ts). Newest first; the newest is shown in full. */
export default async function AgentPage() {
  let rows: Row[] = [];
  try {
    rows = (await sql`SELECT id, created_at, task, status, cost_usd, turns, report FROM agent_reports
                      ORDER BY created_at DESC LIMIT 12`) as unknown as Row[];
  } catch {
    rows = []; // table is created by the first master-agent run
  }
  const [latest, ...older] = rows;
  return (
    <main className="mx-auto max-w-3xl px-4 py-8">
      <h1 className="text-xl font-semibold">Master agent</h1>
      <p className="mt-1 text-sm text-muted">
        Thursday and Sunday runs, plus anything dispatched by hand from GitHub Actions (master-agent workflow).
      </p>
      {!latest ? (
        <p className="mt-6 text-sm text-muted">No reports yet.</p>
      ) : (
        <>
          <div className="card mt-6 p-4">
            <div className="text-sm text-muted">
              {latest.task} · {latest.status} · {ago(latest.created_at)}
              {latest.cost_usd ? ` · $${Number(latest.cost_usd).toFixed(2)}` : ""}
            </div>
            <pre className="mt-3 whitespace-pre-wrap break-words font-sans text-sm leading-relaxed">{latest.report}</pre>
          </div>
          {older.length > 0 && (
            <div className="mt-8 space-y-3">
              <h2 className="text-sm font-semibold text-muted">Earlier runs</h2>
              {older.map((r) => (
                <details key={r.id} className="card p-3">
                  <summary className="cursor-pointer text-sm">
                    {r.task} · {r.status} · {ago(r.created_at)}
                    {r.cost_usd ? ` · $${Number(r.cost_usd).toFixed(2)}` : ""}
                  </summary>
                  <pre className="mt-2 whitespace-pre-wrap break-words font-sans text-sm">{r.report}</pre>
                </details>
              ))}
            </div>
          )}
        </>
      )}
    </main>
  );
}
