import { NextResponse, type NextRequest } from "next/server";
import { SITE_COOKIE, sitePassword, siteToken } from "./lib/site-auth";

/** Members-only gate for the whole site (DECISIONS: site went private 2026-11-07).
 *  Pages without the members cookie redirect to /unlock; API routes return 401. */
export async function proxy(req: NextRequest) {
  const pw = sitePassword();
  const cookie = req.cookies.get(SITE_COOKIE)?.value;
  if (pw && cookie && cookie === (await siteToken(pw))) return NextResponse.next();

  const { pathname, search } = req.nextUrl;
  if (pathname.startsWith("/api/")) {
    return NextResponse.json({ error: "members only" }, { status: 401 });
  }
  const url = req.nextUrl.clone();
  url.pathname = "/unlock";
  url.search = "";
  url.searchParams.set("next", pathname + search);
  return NextResponse.redirect(url);
}

export const config = {
  matcher: ["/((?!unlock|api/unlock|_next/static|_next/image|favicon.ico|robots.txt).*)"],
};
