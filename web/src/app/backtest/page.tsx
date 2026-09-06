import type { Metadata } from "next";
import { BacktestLab } from "@/components/BacktestLab";

export const metadata: Metadata = { title: "Backtest" };
export const dynamic = "force-dynamic";

export default function BacktestPage() {
  return (
    <div className="space-y-6">
      <section>
        <p className="eyebrow">Historical performance</p>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight sm:text-3xl">Backtest</h1>
        <p className="mt-1 max-w-2xl text-[14px] leading-relaxed text-muted">
          The screener&apos;s rules, replayed on prior seasons at real closing lines. Change the edge requirement or the Kelly settings and
          the whole history re-runs — this is how the market bars and the default sizing were chosen, so treat a setting that looks
          better here as something to be suspicious of until it holds up live.
        </p>
      </section>
      <BacktestLab />
    </div>
  );
}
