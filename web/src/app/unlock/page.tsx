export const dynamic = "force-dynamic";
export const metadata = {
  title: "Members only · NFL Edge Finder",
  robots: { index: false, follow: false },
};

export default async function UnlockPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string; e?: string }>;
}) {
  const sp = await searchParams;
  const next = sp.next && sp.next.startsWith("/") && !sp.next.startsWith("//") ? sp.next : "/";
  return (
    <main className="mx-auto flex min-h-[60vh] max-w-sm flex-col justify-center px-4 py-12">
      <h1 className="text-xl font-semibold text-zinc-100">Members only</h1>
      <p className="mt-2 text-sm text-zinc-400">
        Enter this week&apos;s password. Members get it in the Discord.
      </p>
      <form method="post" action="/api/unlock" className="mt-6 space-y-3">
        <input type="hidden" name="next" value={next} />
        <input
          type="password"
          name="password"
          required
          autoFocus
          autoComplete="current-password"
          placeholder="Password"
          className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-zinc-100 outline-none focus:border-zinc-400"
        />
        {sp.e ? <p className="text-sm text-red-400">Wrong password.</p> : null}
        <button
          type="submit"
          className="w-full rounded-md bg-zinc-100 px-3 py-2 font-medium text-zinc-900 hover:bg-white"
        >
          Enter
        </button>
      </form>
    </main>
  );
}
