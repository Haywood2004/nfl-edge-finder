import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "NFL Edge Finder",
  description: "Matchup-aware NFL betting edges with the reasons spelled out.",
};

const nav = [
  { href: "/", label: "This Week" },
  { href: "/board", label: "Full Board" },
  { href: "/rankings/defense", label: "Defense" },
  { href: "/track-record", label: "Track Record" },
];

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="min-h-full flex flex-col">
        <header className="sticky top-0 z-10 border-b border-border bg-bg/90 backdrop-blur">
          <div className="mx-auto flex max-w-5xl items-center gap-4 px-4 py-3">
            <Link href="/" className="whitespace-nowrap font-semibold tracking-tight">
              <span className="text-accent">NFL</span> Edge Finder
            </Link>
            <nav className="ml-auto flex gap-1 overflow-x-auto whitespace-nowrap text-sm">
              {nav.map((n) => (
                <Link key={n.href} href={n.href} className="rounded px-2.5 py-1.5 text-muted hover:bg-panel hover:text-fg">
                  {n.label}
                </Link>
              ))}
            </nav>
          </div>
        </header>
        <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-5">{children}</main>
        <footer className="border-t border-border px-4 py-6 text-center text-xs text-muted">
          <p>Informational only — not financial advice. Nothing here is a lock or a guarantee. Bet responsibly.</p>
          <p className="mt-1">If you or someone you know has a gambling problem, call <span className="text-fg">1-800-GAMBLER</span>.</p>
          <p className="mt-2">Data: nflverse · The Odds API · Open-Meteo. All published picks are graded and shown, wins and losses.</p>
        </footer>
      </body>
    </html>
  );
}
