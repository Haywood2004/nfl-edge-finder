"""In-game tracker. Free part (always on): poll ESPN for games in progress, store state changes in live_game_state,
compute paper in-game projections for every player with a pre-game projection and store them in live_projections.
Paid part (LIVE_INGAME_ENABLED): poll live prop lines for those events, price them with the live (mean, sd) through the
same residual-ECDF P(over) as pre-game, alert on edges, and schedule CLV checks 30 s later and at the next dead ball.
"""
from __future__ import annotations
import datetime as dt
import time
import pandas as pd
from nfl_edge import db
from . import config as C
from .alerts import Alerter
from .espn import ESPN
from .ingame import project, clock_to_seconds
from .odds import LiveOddsAPI, Budget, LineStore
from .pricing import WeekContext, Candidate, norm_name, bar_for

MARKET_STAT = {"player_pass_yds": ("pass_yds", "pass_att", "pass_att", None),
               "player_reception_yds": ("rec_yds", "tgt", "pass_att", "tgt_share_ewm"),
               "player_receptions": ("rec", "tgt", "pass_att", "tgt_share_ewm"),
               "player_rush_yds": ("rush_yds", "rush_att", "rush_att", "carry_share_ewm")}


class Tracker:
    def __init__(self, ctx: WeekContext | None = None, api: LiveOddsAPI | None = None, alerter: Alerter | None = None,
                 espn: ESPN | None = None):
        self.ctx = ctx or WeekContext()
        self.api = api or LiveOddsAPI()
        self.alerter = alerter or Alerter()
        self.espn = espn or ESPN()
        self.budget = Budget()
        self.store = LineStore()
        self.last_state: dict[str, tuple] = {}        # espn_id → signature of the last stored state
        self.last_odds_poll: dict[str, float] = {}
        self.pending_clv: list[dict] = []
        self.espn_map = self._espn_ids()
        self.game_by_teams = {(r.home_team, r.away_team): r.game_id for r in self.ctx.games.itertuples()}
        self.event_by_game = {g: e for e, g in self.ctx.events.items()}
        self.team_off = self._team_offense()

    def _espn_ids(self) -> dict[str, str]:
        r = db.read_sql("SELECT espn_id, gsis_id FROM raw_rosters WHERE season=:s AND espn_id IS NOT NULL", {"s": self.ctx.season})
        return dict(zip(r.espn_id.astype(str), r.gsis_id))

    def _team_offense(self) -> dict[str, dict]:
        r = db.read_sql("SELECT team, plays_pg, pass_rate FROM feat_team_offense WHERE season=:s AND week=:w", {"s": self.ctx.season, "w": self.ctx.week})
        return {x.team: {"plays_pg": float(x.plays_pg) if pd.notna(x.plays_pg) else None, "pass_rate": float(x.pass_rate) if pd.notna(x.pass_rate) else None}
                for x in r.itertuples()}

    # ---------------------------------------------------------------- state
    def live_games(self) -> list[dict]:
        return [g for g in self.espn.scoreboard() if g["state"] == "in"]

    def record_state(self, g: dict, box: dict | None) -> int | None:
        game_id = self.game_by_teams.get((g["home"], g["away"]))
        sig = (g["period"], g["clock"], g["home_score"], g["away_score"],
               (box or {}).get("teams", {}).get(g["home"], {}).get("plays"), (box or {}).get("teams", {}).get(g["away"], {}).get("plays"))
        if self.last_state.get(g["espn_id"]) == sig:
            return None
        self.last_state[g["espn_id"]] = sig
        _, rem = clock_to_seconds(g["period"] or 0, g["clock"] or "0:00")
        teams = (box or {}).get("teams", {})
        sid = db.insert_returning_id("live_game_state", {
            "espn_id": g["espn_id"], "game_id": game_id, "state": g["state"], "period": g["period"], "clock_sec": int(rem % 900) if g["period"] and g["period"] <= 4 else int(rem),
            "home_team": g["home"], "away_team": g["away"], "home_score": g["home_score"], "away_score": g["away_score"],
            "home_plays": teams.get(g["home"], {}).get("plays"), "away_plays": teams.get(g["away"], {}).get("plays"),
            "possession": g.get("possession"), "payload": {"players": list((box or {}).get("players", {}).values()), "teams": teams, "down": g.get("down"), "distance": g.get("distance")}})
        return sid

    # ---------------------------------------------------------------- projections
    def live_projections(self, g: dict, box: dict, state_id: int) -> list[dict]:
        """Paper in-game projection for every (player, market) with a pre-game projection in this game."""
        game_id = self.game_by_teams.get((g["home"], g["away"]))
        if game_id is None or not box:
            return []
        elapsed, remaining = clock_to_seconds(g["period"] or 0, g["clock"] or "15:00")
        by_gsis: dict[str, dict] = {}
        by_name: dict[tuple[str, str], dict] = {}
        for p in box["players"].values():
            gs = self.espn_map.get(p["espn_id"])
            if gs:
                by_gsis[gs] = p
            by_name[(p["team"], norm_name(p["name"] or ""))] = p
        out = []
        for market, proj in self.ctx.proj.items():
            stat_key, opp_key, team_opp_key, share_feat = MARKET_STAT[market]
            for pr in proj[proj.game_id == game_id].itertuples():
                p = by_gsis.get(pr.player_id) or by_name.get((pr.team, pr.nname))
                team = pr.team
                tstats = box["teams"].get(team, {})
                y_t = float(p[stat_key]) if p else 0.0
                player_opps = int(p[opp_key]) if p else 0
                team_opps = int(tstats.get(team_opp_key) or 0)
                plays = int(tstats.get("plays") or 0)
                my_score = g["home_score"] if team == g["home"] else g["away_score"]
                their = g["away_score"] if team == g["home"] else g["home_score"]
                score_diff = float((my_score or 0) - (their or 0))
                X = self.ctx.features.get(pr.player_id, {})
                to = self.team_off.get(team, {})
                lp = project(market, y_t, float(pr.mean), float(pr.sd), plays_so_far=plays, secs_elapsed=elapsed, secs_remaining=remaining,
                             score_diff=score_diff, team_plays_pg=to.get("plays_pg") or X.get("team_plays_pg"), team_pass_rate=to.get("pass_rate") or X.get("team_pass_rate"),
                             team_opps_so_far=team_opps, player_opps_so_far=player_opps,
                             share_pre=(X.get(share_feat) if share_feat else 1.0))
                out.append({"game_state_id": state_id, "game_id": game_id, "player_id": pr.player_id, "player_name": pr.player_name, "market": market,
                            "projection_id": int(pr.id), "y_t": y_t, "f": lp.f, "usage_adj": lp.usage_adj, "script_adj": lp.script_adj,
                            "mean_live": lp.mean_live, "sd_live": lp.sd_live, "_proj": pr, "_lp": lp})
        if out:
            db.append(pd.DataFrame([{k: v for k, v in r.items() if not k.startswith("_")} for r in out]), "live_projections")
        return out

    # ---------------------------------------------------------------- odds (paid)
    def price_live(self, g: dict, projs: list[dict], state_id: int, extra: str):
        game_id = self.game_by_teams.get((g["home"], g["away"]))
        event_id = self.event_by_game.get(game_id)
        if not event_id:
            return
        if time.time() - self.last_odds_poll.get(event_id, 0) < C.INGAME_ODDS_MIN * 60:
            return
        ok, why = self.budget.can_spend(len(C.INGAME_MARKETS))
        if not ok:
            print(f"[ingame] skip odds {g['name']}: {why}"); return
        try:
            payload = self.api.event_odds(event_id, tuple(C.INGAME_MARKETS))
        except Exception as e:
            print(f"[ingame] odds failed {g['name']}: {e}"); self.last_odds_poll[event_id] = time.time(); return
        cost = self.api.last_cost(); self.budget.record(cost, self.api.remaining()); self.last_odds_poll[event_id] = time.time()
        snap_id, live_id, seen = self.store.store("ingame", event_id, game_id, tuple(C.INGAME_MARKETS), payload, cost, self.ctx.season, self.ctx.week,
                                                  is_live=True, game_state_id=state_id, detail={"period": g["period"], "clock": g["clock"]})
        if seen.empty:
            return
        seen["nname"] = seen.player.map(norm_name)
        for r in projs:
            if r["market"] not in C.INGAME_MARKETS:
                continue
            pl = seen[(seen.market == r["market"]) & (seen.nname == r["_proj"].nname)]
            if pl.empty:
                continue
            c = self._price_one(r, pl, event_id, game_id)
            if c is not None and c.clears_bar:
                aid = self.alerter.alert(c, self.ctx, snap_id, live_id, kind="ingame", game_state_id=state_id, extra=extra)
                if aid:
                    self.pending_clv.append({"alert_id": aid, "event_id": event_id, "market": c.market, "player": pl.player.iloc[0], "book": c.book,
                                             "side": c.side, "line": c.line, "market_prob": c.market_prob, "due": time.time() + C.INGAME_CLV_DELAY_SEC,
                                             "horizon": "30s", "period": g["period"], "clock": g["clock"]})

    def _price_one(self, r: dict, pl: pd.DataFrame, event_id: str, game_id: str) -> Candidate | None:
        from nfl_edge.sources.odds_api import american
        from nfl_edge.config import NON_BETTABLE_BOOKS
        model, run_id = self.ctx.models[r["market"]]
        pr, lp = r["_proj"], r["_lp"]
        books = []
        for (book, line), g in pl.groupby(["bookmaker", "line"]):
            if book in NON_BETTABLE_BOOKS:
                continue
            o = g[g.side == "Over"]; u = g[g.side == "Under"]
            if o.empty or u.empty:
                continue
            od, ud = float(o.price_decimal.iloc[0]), float(u.price_decimal.iloc[0]); po, pu = 1 / od, 1 / ud
            books.append({"book": book, "line": float(line), "over_dec": od, "under_dec": ud, "over_fair": po / (po + pu), "under_fair": pu / (po + pu)})
        if not books:
            return None
        best = {}
        for b in books:
            p_over = float(model.p_over(lp.mean_live, lp.sd_live, b["line"]))
            for side, mp, dec, fair in (("Over", p_over, b["over_dec"], b["over_fair"]), ("Under", 1 - p_over, b["under_dec"], b["under_fair"])):
                cand = dict(side=side, model_prob=mp, market_prob=fair, edge=mp - fair, ev=mp * (dec - 1) - (1 - mp), dec=dec, book=b["book"], line=b["line"])
                if side not in best or cand["ev"] > best[side]["ev"]:
                    best[side] = cand
        top = max(best.values(), key=lambda c: c["edge"])
        if top["edge"] <= 0:
            return None
        # confidence: the pre-game card's basis, minus a live penalty (no live calibration yet), minus thin books
        pre = db.read_sql("""SELECT confidence FROM cards WHERE season=:s AND week=:w AND player_id=:p AND market=:m AND source='model'
                             ORDER BY id DESC LIMIT 1""", {"s": self.ctx.season, "w": self.ctx.week, "p": pr.player_id, "m": r["market"]})
        conf = int(pre.confidence.iloc[0]) if len(pre) else 55
        conf = max(0, conf - 5 - (6 if len(books) < 2 else 0))
        meta = self.ctx.feat_meta.get(pr.player_id)
        factors = [{"factor": "bottom_line", "impact": "+", "magnitude": 1.0, "impact_over": 1 if top["side"] == "Over" else -1,
                    "text": f"Live: {r['y_t']:g} so far, {lp.remaining_share:.0%} of expected opportunities left → projected final {lp.mean_live:.0f} "
                            f"(sd {lp.sd_live:.0f}) vs line {top['line']:g}; usage ×{lp.usage_adj:.2f}, script ×{lp.script_adj:.2f}",
                    "source": {"table": "live_projections", "key": "mean_live"}},
                   {"factor": "uncalibrated_live", "impact": "▬", "magnitude": 0.2, "impact_over": 0,
                    "text": "Uncalibrated for live: the pre-game calibrator does not know in-game situations (paper period)", "source": {"table": "model_runs", "key": "calibration"}}]
        return Candidate(player_id=pr.player_id, player_name=pr.player_name, position=meta.position if meta is not None else "", team=pr.team, opponent=pr.opponent,
                         game_id=game_id, event_id=event_id, kickoff_utc=self.ctx._kickoff(game_id), market=r["market"], side=top["side"], line=top["line"],
                         book=top["book"], price_decimal=top["dec"], price_american=american(top["dec"]), model_prob=top["model_prob"], market_prob=top["market_prob"],
                         edge=top["edge"], ev=top["ev"], confidence=conf, prob_calibrated=None, edge_calibrated=None, projection_id=int(pr.id), model_run_id=int(run_id),
                         q50_live=lp.mean_live, sd=lp.sd_live, consensus_line=float(pd.Series([b["line"] for b in books]).median()), open_line=None, n_books=len(books),
                         factors=factors, book_prices=[{"book": b["book"], "line": b["line"], "over": american(b["over_dec"]), "under": american(b["under_dec"])} for b in books])

    # ---------------------------------------------------------------- CLV
    def check_clv(self, live_now: dict[str, dict]):
        """Measure in-game CLV at +30 s and at the next dead ball (clock stopped / period changed)."""
        from .clv import measure_from_lines
        keep = []
        for job in self.pending_clv:
            g = live_now.get(job["event_id"])
            dead_ball = g is not None and (g["clock"] != job["clock"] or g["period"] != job["period"]) and job["horizon"] == "dead_ball"
            if time.time() < job["due"] and not dead_ball:
                keep.append(job); continue
            ok, why = self.budget.can_spend(1)
            if not ok:
                print(f"[clv] skip {job['horizon']}: {why}"); continue
            try:
                payload = self.api.event_odds(job["event_id"], (job["market"],))
            except Exception as e:
                print(f"[clv] odds failed: {e}"); continue
            cost = self.api.last_cost(); self.budget.record(cost, self.api.remaining())
            game_id = self.ctx.events.get(job["event_id"])
            _, live_id, seen = self.store.store("ingame", job["event_id"], game_id, (job["market"],), payload, cost, self.ctx.season, self.ctx.week,
                                                is_live=True, detail={"clv_for": job["alert_id"], "horizon": job["horizon"]})
            measure_from_lines(job["alert_id"], job["horizon"], seen, job["player"], job["book"], job["side"], job["line"], job["market_prob"])
            if job["horizon"] == "30s":
                keep.append(dict(job, horizon="dead_ball", due=time.time() + 600))   # dead ball: next stoppage, at most 10 min
        self.pending_clv = keep

    # ---------------------------------------------------------------- loop
    def tick(self) -> int:
        self.ctx.refresh()
        self.budget.refresh()
        live = self.live_games()
        n = 0
        live_by_event = {}
        for g in live:
            box = self.espn.summary(g["espn_id"])
            sid = self.record_state(g, box)
            game_id = self.game_by_teams.get((g["home"], g["away"]))
            if game_id and self.event_by_game.get(game_id):
                live_by_event[self.event_by_game[game_id]] = g
            if sid is None or not box:
                continue
            projs = self.live_projections(g, box, sid)
            n += len(projs)
            if C.INGAME_ENABLED and projs:
                self.price_live(g, projs, sid, extra=f"Q{g['period']} {g['clock']} {g['away']} {g['away_score']}–{g['home_score']} {g['home']}")
        if C.INGAME_ENABLED:
            self.check_clv(live_by_event)
        self.alerter.flush()
        return n

    def run(self, once: bool = False):
        print(f"[ingame] tracker up; odds polling {'ON' if C.INGAME_ENABLED else 'OFF (paper projections only)'}; {self.budget.summary()}")
        while True:
            try:
                n = self.tick()
                if n:
                    print(f"[ingame] {n} live projections stored")
            except Exception as e:
                print(f"[ingame] tick failed: {e!r}")
            if once:
                self.alerter.flush(force=True); return
            time.sleep(C.INGAME_STATE_SEC)
