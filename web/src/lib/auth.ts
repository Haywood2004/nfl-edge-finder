"use client";
/** Owner login for logging placed bets. The password is checked by /api/placed?check=1 and remembered in localStorage
 *  on this device only; every component that cares listens for the "placed-token" event. */
const KEY = "placed_token";

export function getToken(): string {
  try { return localStorage.getItem(KEY) ?? ""; } catch { return ""; }
}

export function setToken(t: string) {
  try { if (t) localStorage.setItem(KEY, t); else localStorage.removeItem(KEY); } catch {}
  window.dispatchEvent(new CustomEvent("placed-token", { detail: t }));
}

export async function login(): Promise<boolean> {
  const pw = window.prompt("Password:");
  if (!pw) return false;
  const r = await fetch("/api/placed?check=1", { headers: { "x-placed-token": pw } });
  if (r.status !== 204) { alert("Wrong password."); return false; }
  setToken(pw);
  return true;
}

export function logout() { setToken(""); }
