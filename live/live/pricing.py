"""Price a set of live lines exactly the way pipeline/nfl_edge/scoring/cards.py prices a snapshot.

Inputs (read-only, from the shared DB):
  projections     latest row per (season, week, player_id, market) from the newest model_runs for that market
                  (quantiles are stored AFTER level/market anchoring; `mean` is the raw model mean)
  model_runs      the pickled model → its empirical standardised-residual CDF gives P(over)
  feat_player_game features (for confidence + calibration), raw_weather, raw_injuries, odds_lines (open + sharp)
  calibration     latest `market='calibration'` model_run → P(win)

The projection's anchored median is re-anchored to the CURRENT consensus line with the same MARKET_ANCHOR_W the
scorer used (DECISIONS.md, live-bot entries): q50_live = q50_stored + w·(cons_now − cons_at_scoring).
Everything else — P(over) from the model's residual ECDF, no-vig fair probability per book, best-EV book per side,
the confidence function, the sharp ±, the calibrator — is the pipeline's own code, imported, not re-implemented.
"""
from __future__ import annotations
import datetime as dt
import json
import re
import threading
import time
from dataclasses import dataclass, field
import numpy as np
import pandas as pd
from nfl_edge import db
from nfl_edge.config import MARKET_ANCHOR_W, NON_BETTABLE_BOOKS, SHARP_BOOK, SHARP_SNAPSHOT_LABELS, PUBLISH_MIN_EDGE_BY_MARKET, PUBLISH_MIN_EDGE_PROPS, PUBLISH_MIN_CONFIDENCE
from nfl_edge.sources.odds_api import american
from nfl_edge.models.passing_yards import load_latest as load_latest_py, MARKET as PASS_MARKET
from nfl_edge.models.player_props import load_latest as load_latest_prop, SPECS
from nfl_edge.models.calibration import load_latest as load_calibrator, featurize as cal_featurize
from nfl_edge.scoring.factors import confidence_score
from nfl_edge.scoring.skill_factors import skill_confidence
from nfl_edge.ingest.odds_jobs import target_week

MARKETS = [PASS_MARKET] + list(SPECS)


def norm_name(s: str) -> str:
    s = re.sub(r"[^a-z ]", "", str(s).lower())
    s = re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", s)
    return " ".join(s.split())


def bar_for(market: str) -> float:
    return PUBLISH_MIN_EDGE_BY_MARKET.get(market, PUBLISH_MIN_EDGE_PROPS)


@dataclass
class Candidate:
    """One priced (player, market, side): the best-EV bettable book at this poll."""
    player_id: str
    player_name: str
    position: str
    team: str
    opponent: str
    game_id: str
    event_id: str
    kickoff_utc: dt.datetime
    market: str
    side: str
    line: float
    book: str
    price_decimal: float
    price_american: int
    model_prob: float
    market_prob: float
    edge: float
    ev: float
    confidence: int
    prob_calibrated: float | None
    edge_calibrated: float | None
    projection_id: int
    model_run_id: int
    q50_live: float
    sd: float
    consensus_line: float
    open_line: float | None
    n_books: int
    factors: list[dict] = field(default_factory=list)
    book_prices: list[dict] = field(default_factory=list)

    @property
    def clears_bar(self) -> bool:
        return self.edge >= bar_for(self.market) and self.confidence >= PUBLISH_MIN_CONFIDENCE

    @property
    def near_bar(self) -> bool:
        from .config import NEAR_BAR_MARGIN
        return self.edge >= bar_for(self.market) - NEAR_BAR_MARGIN

    @property
    def dedupe_key(self) -> str:
        return f"{self.player_id}|{self.market}|{self.side}|{self.book}|{self.line:g}"


class WeekContext:
    """Everything the pricer needs for one (season, week), loaded from the DB and refreshed every `ttl` seconds."""

    def __init__(self, season: int | None = None, week: int | None = None, ttl: int = 600):
        if season is None or week is None:
            season, week = target_week()
        self.season, self.week, self.ttl = season, week, ttl
        self.lock = threading.RLock()
        self.loaded_at = 0.0
        self.models: dict[str, tuple[object, int]] = {}
        self.calibrator = None
        self.proj: dict[str, pd.DataFrame] = {}
        self.features: dict[str, dict] = {}
        self.open_line: dict[tuple[str, str], float] = {}
        self.sharp: dict[tuple[str, str], dict] = {}
        self.weather: dict[str, dict] = {}
        self.injury: dict[str, dict] = {}
        self.injury_data_available = False
        self.events: dict[str, str] = {}      # event_id → game_id
        self.games: pd.DataFrame = pd.DataFrame()
        self.refresh(force=True)

    # ------------------------------------------------------------------ loading
    def refresh(self, force: bool = False) -> bool:
        if not force and time.time() - self.loaded_at < self.ttl:
            return False
        with self.lock:
            return self._refresh()

    def _refresh(self) -> bool:
        s, w = self.season, self.week
        for m in MARKETS:
            try:
                self.models[m] = load_latest_py() if m == PASS_MARKET else load_latest_prop(m)
            except RuntimeError as e:
                print(f"[pricing] {m}: {e}")
        self.calibrator = load_calibrator()
        self.games = db.read_sql("""SELECT game_id, home_team, away_team, kickoff_utc FROM raw_games
                                    WHERE season=:s AND week=:w AND game_type='REG'""", {"s": s, "w": w})
        self.games["kickoff_utc"] = pd.to_datetime(self.games.kickoff_utc, utc=True)
        ev = db.read_sql("SELECT event_id, game_id FROM odds_events WHERE game_id = ANY(:g)", {"g": self.games.game_id.tolist()})
        self.events = dict(zip(ev.event_id, ev.game_id))
        # latest projection per (player, market) from the newest run of that market
        p = db.read_sql("""SELECT DISTINCT ON (p.market, p.player_id) p.*, r.id AS run_id
                           FROM projections p JOIN model_runs r ON r.id = p.model_run_id
                           WHERE p.season=:s AND p.week=:w AND p.market = ANY(:m)
                           ORDER BY p.market, p.player_id, p.model_run_id DESC, p.id DESC""",
                        {"s": s, "w": w, "m": MARKETS})
        if len(p):
            p["nname"] = p.player_name.map(norm_name)
            for c in ("mean", "sd", "q10", "q25", "q50", "q75", "q90"):
                p[c] = p[c].astype(float)
            p["cons_at_scoring"] = self._consensus_at_scoring(p)
        self.proj = {m: g.reset_index(drop=True) for m, g in p.groupby("market")} if len(p) else {}
        f = db.read_sql("""SELECT player_id, position, team, opponent, is_home, kickoff_utc, features
                           FROM feat_player_game WHERE season=:s AND week=:w""", {"s": s, "w": w})
        self.features = {r.player_id: (json.loads(r.features) if isinstance(r.features, str) else r.features) for r in f.itertuples()}
        self.feat_meta = {r.player_id: r for r in f.itertuples()}
        # open line: the first snapshot of the week per market (pipeline snapshots only)
        ol = db.read_sql("""SELECT l.market, l.player, l.line FROM odds_lines l JOIN odds_snapshots o ON o.id = l.snapshot_id
                            WHERE o.id IN (SELECT DISTINCT ON (m) id FROM (SELECT id, taken_at, unnest(markets) AS m FROM odds_snapshots
                                           WHERE season=:s AND week=:w AND label NOT LIKE 'live%%') x ORDER BY m, taken_at ASC)
                              AND l.player IS NOT NULL""", {"s": s, "w": w})
        self.open_line = {}
        if len(ol):
            ol["nname"] = ol.player.map(norm_name)
            for (m, n), g in ol.groupby(["market", "nname"]):
                self.open_line[(m, n)] = float(g.line.astype(float).median())
        # sharp reference: Pinnacle main line from the most recent labelled snapshot
        sh = db.read_sql("""SELECT l.market, l.player, l.side, l.line, l.price_decimal FROM odds_lines l
                            JOIN odds_snapshots o ON o.id = l.snapshot_id
                            WHERE o.season=:s AND o.week=:w AND l.bookmaker=:b AND l.player IS NOT NULL
                              AND o.id = (SELECT max(id) FROM odds_snapshots WHERE season=:s AND week=:w AND label = ANY(:lab))""",
                         {"s": s, "w": w, "b": SHARP_BOOK, "lab": list(SHARP_SNAPSHOT_LABELS)})
        self.sharp = {}
        if len(sh):
            sh["nname"] = sh.player.map(norm_name)
            for (m, n), g in sh.groupby(["market", "nname"]):
                best = None
                for line, gg in g.groupby("line"):
                    o = gg[gg.side == "Over"]; u = gg[gg.side == "Under"]
                    if o.empty or u.empty:
                        continue
                    od, ud = float(o.price_decimal.iloc[0]), float(u.price_decimal.iloc[0])
                    if best is None or abs(od - ud) < abs(best["over_dec"] - best["under_dec"]):
                        po, pu = 1 / od, 1 / ud
                        best = {"line": float(line), "over_dec": od, "under_dec": ud, "over_fair": po / (po + pu)}
                if best:
                    self.sharp[(m, n)] = best
        wdf = db.read_sql("""SELECT DISTINCT ON (game_id) game_id, wind_mph, temp_f, precip_prob, is_dome
                             FROM raw_weather ORDER BY game_id, fetched_at DESC""")
        self.weather = {r.game_id: {k: (None if pd.isna(v) else v) for k, v in r._asdict().items() if k != "Index"} for r in wdf.itertuples()}
        inj = db.read_sql("""SELECT DISTINCT ON (gsis_id) gsis_id, report_status, practice_status, report_primary_injury
                             FROM raw_injuries WHERE season=:s AND week=:w ORDER BY gsis_id, observed_at DESC""", {"s": s, "w": w})
        self.injury = inj.set_index("gsis_id").to_dict("index") if len(inj) else {}
        self.injury_data_available = bool(len(inj))
        self.loaded_at = time.time()
        n = sum(len(v) for v in self.proj.values())
        print(f"[pricing] context {s} wk{w}: {n} projections, {len(self.models)} models, calibrator={'yes' if self.calibrator else 'no'}, "
              f"{len(self.events)} events, sharp={len(self.sharp)}, open={len(self.open_line)}")
        return True

    def _consensus_at_scoring(self, p: pd.DataFrame) -> pd.Series:
        """Median US-book line for the player at the snapshot the scorer priced this projection against."""
        c = db.read_sql("""SELECT DISTINCT ON (projection_id) projection_id, snapshot_id FROM cards
                           WHERE projection_id = ANY(:ids) ORDER BY projection_id, id""", {"ids": [int(x) for x in p.id]})
        snap_of = dict(zip(c.projection_id, c.snapshot_id))
        snaps = sorted({int(x) for x in snap_of.values() if pd.notna(x)})
        if not snaps:
            return pd.Series([np.nan] * len(p), index=p.index)
        ln = db.read_sql("""SELECT snapshot_id, market, player, line FROM odds_lines WHERE snapshot_id = ANY(:s)
                            AND player IS NOT NULL AND bookmaker <> ALL(:nb)""", {"s": snaps, "nb": list(NON_BETTABLE_BOOKS)})
        ln["nname"] = ln.player.map(norm_name)
        med = ln.groupby(["snapshot_id", "market", "nname"]).line.median()
        out = []
        for r in p.itertuples():
            sid = snap_of.get(int(r.id))
            out.append(float(med.get((int(sid), r.market, r.nname), np.nan)) if sid is not None and pd.notna(sid) else np.nan)
        return pd.Series(out, index=p.index)

    # ------------------------------------------------------------------ pricing
    def price(self, market: str, event_id: str, lines: pd.DataFrame, now: dt.datetime | None = None) -> list[Candidate]:
        """`lines`: rows with bookmaker, player, side, line, price_decimal for ONE event and market."""
        with self.lock:
            return self._price(market, event_id, lines, now)

    def _price(self, market: str, event_id: str, lines: pd.DataFrame, now: dt.datetime | None = None) -> list[Candidate]:
        if market not in self.models or market not in self.proj or lines.empty:
            return []
        game_id = self.events.get(event_id)
        if game_id is None:
            return []
        model, run_id = self.models[market]
        proj = self.proj[market]
        proj = proj[proj.game_id == game_id]
        if proj.empty:
            return []
        now = now or dt.datetime.now(dt.timezone.utc)
        lines = lines.copy()
        lines["nname"] = lines.player.map(norm_name)
        lines["line"] = lines.line.astype(float)
        lines["price_decimal"] = lines.price_decimal.astype(float)
        out: list[Candidate] = []
        for pr in proj.itertuples():
            pl = lines[lines.nname == pr.nname]
            if pl.empty:
                continue
            books = []
            for (book, line), g in pl.groupby(["bookmaker", "line"]):
                if book in NON_BETTABLE_BOOKS:
                    continue
                o = g[g.side == "Over"]; u = g[g.side == "Under"]
                if o.empty or u.empty:
                    continue
                od, ud = float(o.price_decimal.iloc[0]), float(u.price_decimal.iloc[0])
                po, pu = 1 / od, 1 / ud
                books.append({"book": book, "line": float(line), "over_dec": od, "under_dec": ud,
                              "over_american": american(od), "under_american": american(ud),
                              "over_fair": po / (po + pu), "under_fair": pu / (po + pu)})
            if not books:
                continue
            cons_now = float(np.median([b["line"] for b in books]))
            sd = float(pr.sd)
            # re-anchor the stored (anchored) median to the current consensus with the scorer's weight
            shift = MARKET_ANCHOR_W * (cons_now - float(pr.cons_at_scoring)) if pd.notna(pr.cons_at_scoring) else 0.0
            q50_live = float(pr.q50) + shift
            used_mean = q50_live - float(model._zq(0.5)) * sd     # mean ↔ median offset of the residual shape
            X = self.features.get(pr.player_id, {})
            meta = self.feat_meta.get(pr.player_id)
            position = meta.position if meta is not None else ("QB" if market == PASS_MARKET else "")
            kickoff = pd.Timestamp(meta.kickoff_utc).to_pydatetime() if meta is not None else self._kickoff(game_id)
            open_line = self.open_line.get((market, pr.nname))
            wx = self.weather.get(game_id)
            inj = self.injury.get(pr.player_id)
            sharp = self.sharp.get((market, pr.nname))
            sharp_imp = 0
            sharp_factor = None
            if sharp:
                unit = 0.5 if market == "player_receptions" else 1.0
                diff = sharp["line"] - cons_now
                lean = sharp["over_fair"] - 0.5
                sharp_imp = 1 if diff >= unit or (abs(diff) < unit and lean >= 0.02) else (-1 if diff <= -unit or (abs(diff) < unit and lean <= -0.02) else 0)
                sharp_factor = {"factor": "sharp_line", "value": round(diff, 1), "impact_over": sharp_imp,
                                "magnitude": min(abs(diff) / (unit * 4), 1) * 0.8 + 0.1,
                                "text": f"Pinnacle (sharp, last labelled snapshot) line {sharp['line']:g} vs US consensus now {cons_now:g}",
                                "source": {"table": "odds_lines", "key": "pinnacle"}}
            best: dict[str, dict] = {}
            for b in books:
                p_over = float(model.p_over(used_mean, sd, b["line"]))
                for side, mp, dec, am, fair in (("Over", p_over, b["over_dec"], b["over_american"], b["over_fair"]),
                                                ("Under", 1 - p_over, b["under_dec"], b["under_american"], b["under_fair"])):
                    ev = mp * (dec - 1) - (1 - mp)
                    cand = dict(side=side, model_prob=mp, market_prob=fair, edge=mp - fair, ev=ev, dec=dec, american=am,
                                book=b["book"], line=b["line"])
                    if side not in best or cand["ev"] > best[side]["ev"]:
                        best[side] = cand
            stored_factors = pr.factors if isinstance(pr.factors, list) else json.loads(pr.factors or "[]")
            for side, c in best.items():
                if c["edge"] <= 0:
                    continue
                conf = (confidence_score(X, c, open_line, wx, inj, self.injury_data_available, len(books), side) if market == PASS_MARKET
                        else skill_confidence(X, c, open_line, wx, inj, self.injury_data_available, len(books), side, market))
                sf = sharp_imp * (1 if side == "Over" else -1)
                if sharp is not None:
                    conf = int(max(0, min(100, conf + (4 if sf > 0 else -6 if sf < 0 else 0))))
                p_cal = edge_cal = None
                if self.calibrator is not None:
                    row = cal_featurize(market, float(c["edge"]), used_mean, sd, float(c["line"]), side, X, sf, float(c["market_prob"]))
                    p_cal = float(self.calibrator.p_win([row])[0])
                    edge_cal = p_cal - float(c["market_prob"])
                gap = q50_live - float(c["line"])
                unit_txt = "" if market == "player_receptions" else " yds"
                sgn = 1 if side == "Over" else -1
                factors = [{"factor": "bottom_line", "value": round(gap, 1), "impact_over": 1 if gap > 0 else -1,
                            "impact": "+" if (gap > 0) == (side == "Over") else "−",
                            "magnitude": min(abs(gap) / max(sd, 1e-6) * 2, 1.0),
                            "text": f"Bottom line: our median {q50_live:.0f} vs line {c['line']:g} ({gap:+.1f}{unit_txt}, {abs(gap) / max(sd, 1e-6):.2f} sd)",
                            "source": {"table": "projections", "key": "q50"}}]
                if open_line is not None and abs(c["line"] - open_line) >= (0.5 if market == "player_receptions" else 0.5):
                    moved = c["line"] - open_line
                    against = moved > 0 if side == "Over" else moved < 0
                    factors.append({"factor": "line_move", "value": round(moved, 1), "impact_over": -1 if moved > 0 else 1,
                                    "impact": "−" if against else "+", "magnitude": min(abs(moved) / max(sd, 1e-6) * 2, 0.6),
                                    "text": f"Line moved {open_line:g} → {c['line']:g} since the Tuesday open ({'against' if against else 'toward'} us)",
                                    "source": {"table": "odds_lines", "key": "open"}})
                if sharp_factor is not None:
                    factors.append(dict(sharp_factor, impact="+" if sf > 0 else "−" if sf < 0 else "▬"))
                if shift:
                    factors.append({"factor": "live_reanchor", "value": round(shift, 1), "impact_over": 1 if shift > 0 else -1,
                                    "impact": "+" if shift * sgn > 0 else "−", "magnitude": 0.1,
                                    "text": f"Consensus line moved {float(pr.cons_at_scoring):g} → {cons_now:g} since scoring; median re-anchored {shift:+.1f}",
                                    "source": {"table": "projections", "key": "market_anchor"}})
                for x in stored_factors[:4]:
                    if x.get("factor") in ("bottom_line", "sharp_line", "projection"):
                        continue
                    factors.append(dict(x, impact=("+" if x.get("impact_over", 0) * sgn > 0 else "−" if x.get("impact_over", 0) * sgn < 0 else "▬")))
                out.append(Candidate(
                    player_id=pr.player_id, player_name=pr.player_name, position=position, team=pr.team, opponent=pr.opponent,
                    game_id=game_id, event_id=event_id, kickoff_utc=kickoff, market=market, side=side, line=float(c["line"]),
                    book=c["book"], price_decimal=float(c["dec"]), price_american=int(c["american"]),
                    model_prob=float(c["model_prob"]), market_prob=float(c["market_prob"]), edge=float(c["edge"]), ev=float(c["ev"]),
                    confidence=int(conf), prob_calibrated=p_cal, edge_calibrated=edge_cal, projection_id=int(pr.id), model_run_id=int(run_id),
                    q50_live=q50_live, sd=sd, consensus_line=cons_now, open_line=open_line, n_books=len(books), factors=factors,
                    book_prices=[{"book": b["book"], "line": b["line"], "over": b["over_american"], "under": b["under_american"]} for b in books]))
        return out

    def _kickoff(self, game_id: str) -> dt.datetime:
        r = self.games[self.games.game_id == game_id]
        return r.kickoff_utc.iloc[0].to_pydatetime() if len(r) else dt.datetime.now(dt.timezone.utc)

    def card_row(self, c: Candidate, snapshot_id: int, published: bool = False) -> dict:
        """A `cards` row (source='live'). Grading needs price_decimal, line, side, market, player_id, game_id, snapshot_id."""
        return {
            "season": self.season, "week": self.week, "game_id": c.game_id, "event_id": c.event_id, "player_id": c.player_id,
            "player_name": c.player_name, "position": c.position, "team": c.team, "opponent": c.opponent, "kickoff_utc": c.kickoff_utc,
            "market": c.market, "side": c.side, "line": c.line, "price_american": c.price_american, "price_decimal": c.price_decimal,
            "book": c.book, "snapshot_id": snapshot_id, "projection_id": c.projection_id, "model_run_id": c.model_run_id,
            "model_prob": c.model_prob, "market_prob": c.market_prob, "edge": c.edge, "ev_per_unit": c.ev, "confidence": c.confidence,
            "score": c.edge * c.confidence, "prob_calibrated": c.prob_calibrated, "edge_calibrated": c.edge_calibrated,
            "published": published, "factors": c.factors, "line_open": c.open_line, "line_open_snapshot_id": None,
            "book_prices": c.book_prices, "source": "live",
        }
