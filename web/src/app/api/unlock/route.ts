import { NextResponse } from "next/server";
import { SITE_COOKIE, sitePassword, siteToken } from "../../../lib/site-auth";

/** POST from the /unlock form. Sets the members cookie (30 days) and returns to the page asked for. */
export async function POST(req: Request) {
  const form = await req.formData();
  const given = String(form.get("password") ?? "");
  const nextRaw = String(form.get("next") ?? "/");
  const next = nextRaw.startsWith("/") && !nextRaw.startsWith("//") ? nextRaw : "/";
  const pw = sitePassword();

  if (!pw || given !== pw) {
    await new Promise((r) => setTimeout(r, 500)); // slow down guessing
    const back = new URL("/unlock", req.url);
    back.searchParams.set("e", "1");
    back.searchParams.set("next", next);
    return NextResponse.redirect(back, 303);
  }

  const res = NextResponse.redirect(new URL(next, req.url), 303);
  res.cookies.set(SITE_COOKIE, await siteToken(pw), {
    httpOnly: true,
    secure: true,
    sameSite: "lax",
    path: "/",
    maxAge: 60 * 60 * 24 * 30,
  });
  return res;
}
