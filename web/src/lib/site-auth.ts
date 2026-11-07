/** Site-wide password gate (members only). The password comes from the SITE_PASSWORD env var,
 *  falling back to PLACED_BETS_TOKEN. If neither is set the site stays locked (fail closed).
 *  The cookie holds a SHA-256 of the password, never the password itself, so rotating the
 *  password in Vercel (then redeploying) logs everyone out. */
export const SITE_COOKIE = "site_auth";

export function sitePassword(): string {
  return process.env.SITE_PASSWORD || process.env.PLACED_BETS_TOKEN || "";
}

export async function siteToken(pw: string): Promise<string> {
  const data = new TextEncoder().encode(`nfl-edge-site:${pw}`);
  const buf = await crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(buf))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}
