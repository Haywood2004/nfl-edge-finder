import { modelCards } from "@/lib/queries";
import { num, pct } from "@/lib/format";

export const dynamic = "force-dynamic";
export const metadata = { title: "Methodology" };

type Cal = { bucket: string; n: number; pred: number; actual: number };

export default async function How() {
  const models = await modelCards();
  const py = models.find((m) => m.market === "player_pass_yds");
  const ml = models.find((m) => m.market === "h2h");
  const h = (py?.metrics as { holdout?: Record<string, unknown> } | undefined)?.holdout as
    | { n: number; mae: number; mae_baseline_ewm: number; mae_baseline_prev_season: number; cov_q10: number; cov_q25: number; cov_q75: number; cov_q90: number; calibration: Cal[] }
    | undefined;
  const mlt = (ml?.metrics as { test_2025?: Record<string, number>; anchor_w?: number; walk_forward_raw_model?: { betting: Record<string, { bets: number; roi: number; win_rate: number }> } } | undefined);

  return (
    <div className="mx-auto max-w-3xl space-y-10">
      <div>
        <p className="eyebrow">Methodology</p>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight sm:text-3xl">How a card gets made</h1>
        <p className="mt-2 text-[15px] leading-relaxed text-muted">
          Most prop tools say &ldquo;Player X averages 250, the line is 240, take the over.&rdquo; That is not an edge — the book already knows the average.
          Every number here goes a layer deeper: what the opponent allows, who is missing on both sides, and what the game environment does to volume.
        </p>
      </div>

      <ol className="grid gap-3 sm:grid-cols-2">
        <Step n={1} title="Point-in-time features" body="Player form (rolling and exponentially-weighted yards, attempts, EPA, CPOE, air yards, sack rate), the opponent's schedule-adjusted pass defense (yards and EPA per dropback, pressure, explosive-play and YAC allowed), the offense's script-neutral pass rate and pace, the market's spread, total and implied points, rest, weather and dome status, the injury report on both sides, and whether the coaching staff is new. A feature for Week 9 may only use data that existed before Week 9 kicked off; a test enforces it." />
        <Step n={2} title="A distribution, not a number" body="Two gradient-boosted models: one for the mean, one for the spread. The target is modelled relative to the league's passing environment so era drift cannot bias it, and the residual shape is taken from held-out seasons rather than assumed Normal. That gives a real probability for any line, not just a projection." />
        <Step n={3} title="Priced against every venue" body="Lines are snapshotted from every US book (and Polymarket for moneylines) on a fixed schedule and never overwritten. Each book's hold is removed to get a fair probability; the edge is the model's probability minus the fair probability at the best available price. Projections are anchored partly toward the market, because the books price things a stats model cannot see." />
        <Step n={4} title="Confidence, then the bar" body="A 0–100 confidence score shrinks the edge for thin samples, new teams, early-season priors, missing injury or weather data, line moves against the pick and implausibly large gaps. A card is flagged at edge ≥ 15% and confidence ≥ 55. Everything else is priced, explained and tracked as a paper bet on the Full Board." />
      </ol>

      {h && (
        <section className="card p-5 sm:p-6">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <div>
              <p className="eyebrow">Model card · passing yards</p>
              <h2 className="h-section mt-1">{py?.version} · held-out {py?.test_seasons?.join("–")}</h2>
            </div>
            <span className="text-[12px] text-muted">retrained {new Date(py!.trained_at).toLocaleDateString("en-US", { month: "short", day: "numeric" })} · trained on {py?.train_seasons?.[0]}–{py?.train_seasons?.at(-1)}</span>
          </div>
          <p className="mt-2 text-[13px] leading-relaxed text-muted">
            Walk-forward protocol: fit on 2016–2022, tune on 2023, report on {py?.test_seasons?.join(" and ")} ({h.n} starter games the model never saw). The production model is then refit through the latest completed week.
          </p>
          <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
            <Kpi label="MAE · model" value={num(h.mae, 1)} sub="yards, held-out" />
            <Kpi label="MAE · player average" value={num(h.mae_baseline_ewm, 1)} sub="what a naive line knows" />
            <Kpi label="MAE · last season" value={num(h.mae_baseline_prev_season, 1)} sub="previous-season mean" />
            <Kpi label="P25 / P75 coverage" value={`${pct(h.cov_q25)} / ${pct(h.cov_q75)}`} sub="ideal 25% / 75%" />
          </div>
          <div className="mt-5">
            <p className="eyebrow mb-2">Calibration — when the model says X%, how often does it hit?</p>
            <div className="space-y-1.5">
              {h.calibration.map((c) => (
                <div key={c.bucket} className="grid grid-cols-[92px_1fr_120px] items-center gap-3 text-[12px]">
                  <span className="text-muted tnum">{c.bucket.replace("(", "").replace("]", "").replace(", ", "–")}</span>
                  <div className="relative h-2.5 rounded-full bg-panel-3">
                    <div className="absolute inset-y-0 left-0 rounded-full bg-accent/35" style={{ width: `${c.pred * 100}%` }} />
                    <div className="absolute top-[-3px] h-4 w-[2px] rounded bg-up" style={{ left: `${c.actual * 100}%` }} title={`actual ${pct(c.actual, 1)}`} />
                  </div>
                  <span className="text-right tnum"><span className="text-muted">pred</span> {pct(c.pred, 1)} <span className="text-muted">· hit</span> <span className="text-up">{pct(c.actual, 1)}</span></span>
                </div>
              ))}
            </div>
            <p className="mt-2 text-[12px] text-dim">Bar = predicted over-probability bucket; green tick = actual over rate at synthetic lines across {h.n} held-out games.</p>
          </div>
        </section>
      )}

      {mlt?.test_2025 && (
        <section className="card p-5 sm:p-6">
          <p className="eyebrow">Model card · moneyline</p>
          <h2 className="h-section mt-1">{ml?.version} · why moneyline cards flag prices, not opinions</h2>
          <p className="mt-2 text-[13px] leading-relaxed text-muted">
            An Elo + EPA ratings model with rest, divisional, QB-change and home-field terms. Bet against real closing moneylines from 2019–2025, the raw model <em>loses</em> at every edge threshold
            {mlt.walk_forward_raw_model && ` (≥15% edge: ${mlt.walk_forward_raw_model.betting["edge>=0.15"].bets} bets, ${pct(mlt.walk_forward_raw_model.betting["edge>=0.15"].roi, 1)} ROI)`}.
            So the blend is {pct(mlt.anchor_w ?? 0.95)} toward the sportsbook consensus, and a moneyline card appears only when one venue — often Polymarket — pays more than that blended probability implies.
          </p>
          <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
            <Kpi label="Log-loss · blend" value={num(mlt.test_2025.logloss_used, 3)} sub="2025 held-out" />
            <Kpi label="Log-loss · market" value={num(mlt.test_2025.logloss_market, 3)} sub="closing no-vig" />
            <Kpi label="Accuracy · market" value={pct(mlt.test_2025.accuracy_market, 1)} sub="picking the winner" />
            <Kpi label="Games" value={String(mlt.test_2025.n)} sub="2025 regular season" />
          </div>
        </section>
      )}

      <section className="prose text-[14px] text-fg-2">
        <h2 className="h-section">What &ldquo;edge&rdquo; and &ldquo;confidence&rdquo; mean</h2>
        <p><b className="text-fg">Edge</b> is the model probability minus the no-vig implied probability at the best available price. At −110 the fair probability is 50%, so a 62% model probability is a +12% edge. <b className="text-fg">EV</b> is the expected profit per dollar at that price.</p>
        <p><b className="text-fg">Confidence</b> starts near 70 and is reduced by concrete, listed penalties: fewer than 20 career starts, a new team, no current-season opponent data, an injury report or forecast that has not been published, a line that moved against the pick since the open, and edges so large they are more likely model error than book error. It is not a feeling; every deduction is visible in the factor list.</p>
        <h2 className="h-section">Grading</h2>
        <p>After each week&apos;s games finalize, every flagged pick and every paper bet is graded at the price shown when it was published, and closing-line value records whether the market moved toward the pick. The track record is public, unfiltered, and never edited.</p>
        <p className="text-muted">Informational only — not financial advice. If you or someone you know has a gambling problem, call 1-800-GAMBLER.</p>
      </section>
    </div>
  );
}

function Step({ n, title, body }: { n: number; title: string; body: string }) {
  return (
    <li className="card p-4 sm:p-5">
      <div className="flex items-center gap-2.5">
        <span className="flex h-6 w-6 items-center justify-center rounded-full bg-accent/15 text-[12px] font-semibold text-accent-2">{n}</span>
        <p className="font-medium">{title}</p>
      </div>
      <p className="mt-2 text-[13px] leading-relaxed text-muted">{body}</p>
    </li>
  );
}

function Kpi({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-lg bg-panel-2/70 kpi">
      <div className="kpi-label">{label}</div>
      <div className="kpi-value text-xl">{value}</div>
      {sub && <div className="kpi-sub">{sub}</div>}
    </div>
  );
}
