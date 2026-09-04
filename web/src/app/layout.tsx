import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";
import { Nav, Logo } from "@/components/Nav";
import { StatusPill } from "@/components/Freshness";

export const metadata: Metadata = {
  title: { default: "Edge Finder — matchup-aware NFL betting edges", template: "%s · Edge Finder" },
  description: "NFL player props and moneylines priced against a projection model that accounts for the opponent, injuries and game context — with the record, the edge and the reasons on every card.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="h-full">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet" />
      </head>
      <body className="min-h-full flex flex-col">
        <header className="sticky top-0 z-20 border-b border-border/80 bg-bg/80 backdrop-blur-md">
          <div className="mx-auto flex max-w-6xl items-center gap-3 px-4 py-2.5 sm:gap-6">
            <Logo />
            <div className="hidden sm:block"><Nav /></div>
            <div className="ml-auto"><StatusPill /></div>
          </div>
          <div className="border-t border-border/60 px-2 py-1 sm:hidden"><Nav /></div>
        </header>
        <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6 sm:py-8">{children}</main>
        <footer className="mt-10 border-t border-border">
          <div className="mx-auto grid max-w-6xl gap-8 px-4 py-10 text-sm sm:grid-cols-3">
            <div>
              <Logo />
              <p className="mt-3 max-w-xs text-[13px] leading-relaxed text-muted">
                A projection model that looks at the opponent, the coverage, the injuries and the game environment — then shows its work on every card.
              </p>
            </div>
            <div>
              <p className="eyebrow mb-2">Product</p>
              <ul className="space-y-1.5 text-fg-2">
                <li><Link href="/" className="hover:text-fg">This week&apos;s edges</Link></li>
                <li><Link href="/board" className="hover:text-fg">Full board</Link></li>
                <li><Link href="/track-record" className="hover:text-fg">Track record</Link></li>
                <li><Link href="/how" className="hover:text-fg">Methodology &amp; model card</Link></li>
              </ul>
            </div>
            <div>
              <p className="eyebrow mb-2">Responsible play</p>
              <p className="text-[13px] leading-relaxed text-muted">
                Informational only — not financial advice. Nothing here is a lock or a guarantee, and every published pick is graded and shown, wins and losses.
                If you or someone you know has a gambling problem, call <span className="font-medium text-fg">1-800-GAMBLER</span>.
              </p>
              <p className="mt-3 text-[12px] text-dim">Data: nflverse · The Odds API · Polymarket · Open-Meteo · ESPN</p>
            </div>
          </div>
        </footer>
      </body>
    </html>
  );
}
