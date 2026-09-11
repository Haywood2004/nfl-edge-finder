"use client";
import { useEffect, useState } from "react";
import { getToken, login, logout } from "@/lib/auth";

/** Top-right owner login. When logged in, screener rows get a "placed?" button and Track Record accepts new bets. */
export function LoginButton() {
  const [on, setOn] = useState(false);
  useEffect(() => {
    setOn(!!getToken());
    const h = (e: Event) => setOn(!!(e as CustomEvent).detail);
    window.addEventListener("placed-token", h);
    return () => window.removeEventListener("placed-token", h);
  }, []);
  return on ? (
    <button onClick={logout} className="rounded-md bg-up/15 px-2.5 py-1 text-[12px] font-medium text-up" title="Logged in — bet logging is on. Click to log out.">
      ● Haywood
    </button>
  ) : (
    <button onClick={login} className="rounded-md border border-border px-2.5 py-1 text-[12px] font-medium text-muted hover:text-fg" title="Log in to record the bets you place">
      Log in
    </button>
  );
}
