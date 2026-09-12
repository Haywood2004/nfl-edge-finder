"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

const nav = [
  { href: "/", label: "Screener" },
  { href: "/games", label: "Games" },
  { href: "/cfb", label: "CFB" },
  { href: "/rankings/defense", label: "Defense" },
  { href: "/backtest", label: "Backtest" },
  { href: "/track-record", label: "Track Record" },
  { href: "/how", label: "Methodology" },
];

export function Nav() {
  const path = usePathname();
  return (
    <nav className="flex gap-0.5 overflow-x-auto whitespace-nowrap text-[13px] font-medium">
      {nav.map((n) => {
        const active = n.href === "/" ? path === "/" : path.startsWith(n.href);
        return (
          <Link
            key={n.href}
            href={n.href}
            className={`rounded-md px-2.5 py-1.5 transition-colors ${active ? "bg-panel-2 text-fg" : "text-muted hover:bg-panel-2/70 hover:text-fg"}`}
          >
            {n.label}
          </Link>
        );
      })}
    </nav>
  );
}

export function Logo() {
  return (
    <Link href="/" className="flex items-center gap-2.5 whitespace-nowrap">
      <svg width="26" height="26" viewBox="0 0 26 26" aria-hidden className="shrink-0">
        <defs>
          <linearGradient id="lg" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#5aa8ff" />
            <stop offset="1" stopColor="#2fd19a" />
          </linearGradient>
        </defs>
        <rect x="1" y="1" width="24" height="24" rx="7" fill="url(#lg)" opacity="0.18" stroke="url(#lg)" strokeWidth="1.2" />
        <path d="M6 17 L11 11 L14.5 14 L20 7" fill="none" stroke="url(#lg)" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
        <circle cx="20" cy="7" r="2" fill="#2fd19a" />
      </svg>
      <span className="text-[15px] font-semibold tracking-tight">
        Edge Finder <span className="ml-1 rounded bg-panel-2 px-1.5 py-0.5 align-middle text-[10px] font-semibold tracking-[0.12em] text-muted">NFL</span>
      </span>
    </Link>
  );
}
