import Link from "next/link";
import { MyBets } from "@/components/MyBets";

export const dynamic = "force-dynamic";
export const metadata = { title: "Track record" };

export default function TrackRecord() {
  return (
    <div className="space-y-6">
      <div>
        <p className="eyebrow">Honest ledger</p>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight">Track record</h1>
        <p className="mt-1 max-w-2xl text-sm text-muted">
          The bets actually placed, graded at the price and stake taken. Nothing is removed once it&apos;s settled.
          The model&apos;s own systematic paper record (every pick it flagged, whether or not it was bet) lives on the{" "}
          <Link href="/model-record" className="text-accent hover:underline">model record</Link> page.
        </p>
      </div>
      <MyBets />
    </div>
  );
}
