"""python -m live <job> [options]

  worker      pre-game watcher + in-game tracker in one process (the hosted entrypoint)
  pregame     pre-game watcher only        --once for a single tick
  ingame      in-game tracker only         --once for a single tick
  replay      validate the in-game model on a season's play-by-play → docs/MODEL.md ("Live")
  clv         close out pre-game alerts whose games kicked off (closing line → live_clv)
  report      the weekly numbers for docs/TODO.md (alerts, hit rate, CLV, credits)
  status      budget + context sanity check (no credits spent)
"""
from __future__ import annotations
import argparse
import sys
import threading
import warnings

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)


def main(argv=None):
    p = argparse.ArgumentParser(prog="live")
    p.add_argument("job")
    p.add_argument("--once", action="store_true")
    p.add_argument("--season", type=int, default=2025)
    p.add_argument("--max-games", type=int, default=None)
    p.add_argument("--days", type=int, default=7)
    a = p.parse_args(argv)
    if a.job == "status":
        from .odds import Budget
        from .pricing import WeekContext
        b = Budget(); ctx = WeekContext()
        print(b.summary()); print({m: len(v) for m, v in ctx.proj.items()})
    elif a.job == "pregame":
        from .pregame import Watcher
        Watcher().run(once=a.once)
    elif a.job == "ingame":
        from .tracker import Tracker
        Tracker().run(once=a.once)
    elif a.job == "worker":
        from .pregame import Watcher
        from .tracker import Tracker
        from .pricing import WeekContext
        from .alerts import Alerter
        from .clv import close_pregame_alerts
        ctx, alerter = WeekContext(), Alerter()
        w, t = Watcher(ctx, alerter=alerter), Tracker(ctx, alerter=alerter)
        alerter.notice(f"live bot up — {w.budget.summary()} — paper_only={__import__('live.config', fromlist=['x']).PAPER_ONLY}")
        th = threading.Thread(target=t.run, kwargs={"once": a.once}, daemon=True); th.start()

        def _clv_loop():
            import time
            while True:
                try:
                    close_pregame_alerts()
                except Exception as e:
                    print(f"[clv] {e!r}")
                time.sleep(1800)
        threading.Thread(target=_clv_loop, daemon=True).start()
        w.run(once=a.once)
    elif a.job == "replay":
        from .replay import run
        run(a.season, max_games=a.max_games)
    elif a.job == "clv":
        from .clv import close_pregame_alerts
        close_pregame_alerts()
    elif a.job == "report":
        from .clv import report
        report(a.days)
    else:
        print(f"unknown job {a.job}", file=sys.stderr); return 2
    return 0
