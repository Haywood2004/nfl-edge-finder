"""L3 Defense vs. Line experiment (DECISIONS #43–#46). Pure pandas: no DB, so tests and the backtest share one path.

Two versions, both graded:

naive_v0  Haywood's rule as stated. A defense's last-3-games yards allowed per game (TeamRankings "Last 3": net
          passing yards = passing yards minus sack yards; rushing yards = every rushing play incl. scrambles/kneels)
          ranked 1–32 (1 = fewest). Ranks 25–32 = SOFT, 1–8 = STINGY (pre-registered cut-offs). The opposing QB
          (passing yards) or RB (rushing yards): line < his last-3 average and defense SOFT → Over; line > his
          last-3 average and defense STINGY → Under.

l3_v1     Same idea, built so it can be wrong in a measurable way: per-play efficiency instead of totals,
          opponent-adjusted, shrunk with empirical Bayes, a statistical (not rank) definition of soft/stingy,
          and a player projection with a distribution, priced against the no-vig market.

Point-in-time: everything for (season S, week W) uses games with week < W in season S plus earlier seasons only.
"""
from __future__ import annotations
import math
import re
from dataclasses import dataclass, field
import numpy as np
import pandas as pd

PASS_MKT, RUSH_MKT = "player_pass_yds", "player_rush_yds"
VERSIONS = ("naive_v0", "naive_g10", "l3_v1")

# ---- pre-registered constants (DECISIONS #44). Changing any of these after seeing a backtest is a new version. ----
NAIVE_STINGY_MAX_RANK = 8
NAIVE_SOFT_MIN_RANK = 25
NAIVE_MIN_GAMES = 3          # the rule is a last-3 rule; with <3 games it does not fire
V1_Z = 1.0                   # shrunk, opponent-adjusted L3 beyond ±1 SD of that week's league distribution
V1_CI_Z = 1.2816             # …and the 80% interval excludes league average
V1_MIN_EDGE = 0.03           # model P(side) − no-vig market P(side) at the best bettable price
NAIVE_GATE = 0.10           # naive_g10 (Haywood, 2026-10-04): |player L3 − line| ≥ 10% of the line, else no flag
BACKTEST_MIN_WEEK = 4        # the L3 inputs only exist from Week 4 (3 games played); backtests start there
FLAT_DEC = 1 + 100 / 110     # −110 both sides, for the "what if every pick were −110" P&L
LEAN_MIN_BETS = 150          # publishing rule: "lean" only with ≥150 graded backtest bets…
LEAN_MIN_CI_LO = -0.02       # …and the 95% CI lower bound of ROI at closing price above −2%

# per-play stats: name → (numerator column, denominator column, side)
STATS = {
    "pass_ypd": ("pass_yds_net", "dropbacks", "pass"),
    "pass_epa": ("pass_epa", "dropbacks", "pass"),
    "pass_sr": ("pass_succ", "dropbacks", "pass"),
    "rush_ypc": ("rush_yds_d", "carries_d", "rush"),
    "rush_epa": ("rush_epa", "carries_d", "rush"),
    "rush_sr": ("rush_succ", "carries_d", "rush"),
}
PRIMARY = {"pass": "pass_ypd", "rush": "rush_ypc"}   # flags are decided on these; EPA/SR are shown alongside
MARKET_SIDE = {PASS_MKT: "pass", RUSH_MKT: "rush"}

# Fallback EB parameters, used only until `python -m nfl_edge backtest_l3` has fitted l3_params.json.
DEFAULT_PARAMS = {
    "pass_ypd": {"rho": 0.35, "tau2": 0.35, "sigma2": 75.0},
    "pass_epa": {"rho": 0.35, "tau2": 0.004, "sigma2": 2.3},
    "pass_sr": {"rho": 0.35, "tau2": 0.0008, "sigma2": 0.245},
    "rush_ypc": {"rho": 0.35, "tau2": 0.12, "sigma2": 40.0},
    "rush_epa": {"rho": 0.35, "tau2": 0.002, "sigma2": 1.0},
    "rush_sr": {"rho": 0.35, "tau2": 0.0008, "sigma2": 0.24},
}


def norm_name(s: str) -> str:
    s = re.sub(r"[^a-z ]", "", str(s).lower())
    s = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", s)
    return " ".join(s.split())


# =============================================================== team-game aggregates from play-by-play
def team_games(pbp: pd.DataFrame) -> pd.DataFrame:
    """One row per (game, defense). Columns reproduce TeamRankings' per-game totals exactly (checked on 2026 Weeks
    1–4: net passing max |diff| 0.03 yd, rushing 0.03 yd) plus per-play sums for the efficiency stats."""
    p = pbp[pbp.season_type.fillna("REG") == "REG"].copy() if "season_type" in pbp else pbp.copy()
    p = p[p.defteam.notna() & p.posteam.notna()]
    for c in ("qb_dropback", "qb_scramble", "sack", "rush", "pass"):
        p[c] = p[c].fillna(0).astype(int) if c in p else 0
    for c in ("passing_yards", "rushing_yards", "yards_gained", "epa", "success"):
        p[c] = pd.to_numeric(p[c], errors="coerce").fillna(0.0)
    db = (p.qb_dropback == 1) & (p.qb_scramble != 1)
    designed = (p.rush == 1) & (p.qb_scramble != 1) & (p.play_type == "run")
    p["_sack_yds"] = np.where(p.sack == 1, p.yards_gained, 0.0)
    p["_db"] = db.astype(int)
    p["_db_yds"] = np.where(db, p.passing_yards + p._sack_yds, 0.0)
    p["_db_epa"] = np.where(db, p.epa, 0.0)
    p["_db_succ"] = np.where(db, p.success, 0.0)
    p["_dr"] = designed.astype(int)
    p["_dr_yds"] = np.where(designed, p.yards_gained, 0.0)
    p["_dr_epa"] = np.where(designed, p.epa, 0.0)
    p["_dr_succ"] = np.where(designed, p.success, 0.0)
    g = p.groupby(["season", "week", "game_id", "defteam", "posteam"], as_index=False).agg(
        pass_yds_tr=("passing_yards", "sum"), sack_yds=("_sack_yds", "sum"), rush_yds_tr=("rushing_yards", "sum"),
        dropbacks=("_db", "sum"), pass_yds_net=("_db_yds", "sum"), pass_epa=("_db_epa", "sum"), pass_succ=("_db_succ", "sum"),
        carries_d=("_dr", "sum"), rush_yds_d=("_dr_yds", "sum"), rush_epa=("_dr_epa", "sum"), rush_succ=("_dr_succ", "sum"))
    g["pass_yds_tr"] = g.pass_yds_tr + g.sack_yds     # TeamRankings "opponent passing yards" = net of sacks
    return g.drop(columns="sack_yds")


def play_variances(pbp: pd.DataFrame) -> dict[str, float]:
    """Per-play variance of each stat (the σ² in σ²/n)."""
    p = pbp[pbp.season_type.fillna("REG") == "REG"] if "season_type" in pbp else pbp
    db = p[(p.qb_dropback == 1) & (p.qb_scramble != 1)]
    dr = p[(p.rush == 1) & (p.qb_scramble != 1) & (p.play_type == "run")]
    dby = db.passing_yards.fillna(0) + np.where(db.sack == 1, db.yards_gained.fillna(0), 0)
    return {"pass_ypd": float(np.var(dby)), "pass_epa": float(np.nanvar(db.epa)), "pass_sr": float(np.nanvar(db.success)),
            "rush_ypc": float(np.var(dr.yards_gained.fillna(0))), "rush_epa": float(np.nanvar(dr.epa)),
            "rush_sr": float(np.nanvar(dr.success))}


# =============================================================== point-in-time defense table
def _rate(df: pd.DataFrame, stat: str) -> float:
    num, den, _ = STATS[stat]
    d = df[den].sum()
    return float(df[num].sum() / d) if d > 0 else float("nan")


def defense_table(tg: pd.DataFrame, season: int, week: int, params: dict | None = None) -> pd.DataFrame:
    """32 rows for (season, week): raw L3, opponent-adjusted L3, shrunk L3, shrink factor, z, condition.

    tg must hold team_games for `season` and `season-1` (more is fine). Only games with week < `week` in `season`
    (and the whole previous season) are read.
    """
    params = params or DEFAULT_PARAMS
    cur = tg[(tg.season == season) & (tg.week < week)]
    prev = tg[tg.season == season - 1]
    if cur.empty:
        return pd.DataFrame()
    teams = sorted(set(cur.defteam) | set(cur.posteam))
    league_cur = {s: _rate(cur, s) for s in STATS}
    league_prev = {s: _rate(prev, s) for s in STATS} if len(prev) else league_cur
    rows = []
    for t in teams:
        d_games = cur[cur.defteam == t].sort_values("week")
        if d_games.empty:
            continue
        l3 = d_games.tail(3)
        earlier = d_games.iloc[:-3] if len(d_games) > 3 else d_games.iloc[0:0]
        r = {"season": season, "week": week, "team": t, "games": int(len(d_games)), "l3_games": int(len(l3)),
             "l3_opps": ",".join(l3.posteam), "l3_weeks": ",".join(str(int(w)) for w in l3.week),
             "pass_ypg_l3": float(l3.pass_yds_tr.mean()), "rush_ypg_l3": float(l3.rush_yds_tr.mean()),
             "pass_ypg_season": float(d_games.pass_yds_tr.mean()), "rush_ypg_season": float(d_games.rush_yds_tr.mean())}
        for s, (num, den, side) in STATS.items():
            n = float(l3[den].sum())
            raw = _rate(l3, s)
            # opponent adjustment: actual − what this offense normally gains per play (its other games before W)
            exp_num = 0.0
            for _, g in l3.iterrows():
                o_other = cur[(cur.posteam == g.posteam) & (cur.game_id != g.game_id)]
                o_prev = prev[prev.posteam == g.posteam]
                if o_other[den].sum() >= 20:
                    o_rate = _rate(o_other, s)
                    # an offense's own few games are noisy too: weight n/(n+2) on them, the rest on league average
                    k = len(o_other) / (len(o_other) + 2.0)
                    o_rate = k * o_rate + (1 - k) * league_cur[s]
                elif len(o_prev) and o_prev[den].sum() > 0:
                    o_rate = league_cur[s] + 0.5 * (_rate(o_prev, s) - league_prev[s])
                else:
                    o_rate = league_cur[s]
                exp_num += o_rate * g[den]
            adj = float((l3[num].sum() - exp_num) / n) if n > 0 else float("nan")
            # prior information: this defense earlier this season (before the L3 window), else last season
            if len(earlier) and earlier[den].sum() > 0:
                prior_dev = _rate(earlier, s) - league_cur[s]
            else:
                dp = prev[prev.defteam == t]
                prior_dev = (_rate(dp, s) - league_prev[s]) if len(dp) else 0.0
            pr = params.get(s, DEFAULT_PARAMS[s])
            mu = pr["rho"] * prior_dev
            noise = pr["sigma2"] / n if n > 0 else float("inf")
            B = pr["tau2"] / (pr["tau2"] + noise) if n > 0 else 0.0
            shrunk = mu + B * ((adj if adj == adj else mu) - mu)
            post_sd = math.sqrt(B * noise) if n > 0 else math.sqrt(pr["tau2"])
            r.update({f"{s}_n": n, f"{s}_raw": raw, f"{s}_league": league_cur[s], f"{s}_adj": adj,
                      f"{s}_prior_dev": prior_dev, f"{s}_prior": mu, f"{s}_shrink": B, f"{s}_shrunk": shrunk, f"{s}_sd": post_sd})
        rows.append(r)
    out = pd.DataFrame(rows)
    # naive_v0: rank on raw yards per game (1 = fewest allowed)
    for side in ("pass", "rush"):
        out[f"{side}_naive_rank"] = out[f"{side}_ypg_l3"].rank(method="min").astype(int)
        out[f"{side}_naive_cond"] = np.select(
            [(out[f"{side}_naive_rank"] >= NAIVE_SOFT_MIN_RANK) & (out.l3_games >= NAIVE_MIN_GAMES),
             (out[f"{side}_naive_rank"] <= NAIVE_STINGY_MAX_RANK) & (out.l3_games >= NAIVE_MIN_GAMES)],
            ["soft", "stingy"], "")
    # l3_v1: statistical condition on the primary per-play stat
    for s in STATS:
        x = out[f"{s}_shrunk"]
        sd = float(x.std(ddof=0)) or 1e-9
        out[f"{s}_z"] = (x - x.mean()) / sd
        out[f"{s}_rank"] = x.rank(method="min").astype(int)     # 1 = allows the least
    for side, s in PRIMARY.items():
        lo = out[f"{s}_shrunk"] - V1_CI_Z * out[f"{s}_sd"]
        hi = out[f"{s}_shrunk"] + V1_CI_Z * out[f"{s}_sd"]
        out[f"{side}_v1_cond"] = np.select([(out[f"{s}_z"] > V1_Z) & (lo > 0), (out[f"{s}_z"] < -V1_Z) & (hi < 0)],
                                           ["soft", "stingy"], "")
    return out


# =============================================================== player baselines
@dataclass
class Market:
    key: str
    pos: tuple
    yds: str
    vol: str
    min_vol: int          # a game counts as "played" for L3 when volume ≥ this
    train_min_vol: int    # training rows for l3_v1


MARKETS = {
    PASS_MKT: Market(PASS_MKT, ("QB",), "passing_yards", "attempts", 1, 10),
    RUSH_MKT: Market(RUSH_MKT, ("RB",), "rushing_yards", "carries", 1, 5),
}


def player_history(ws: pd.DataFrame, mk: Market) -> pd.DataFrame:
    """Regular-season games with usage for the market's positions; sorted for rolling windows."""
    w = ws[(ws.season_type.fillna("REG") == "REG") & ws.position.isin(mk.pos)].copy()
    w[mk.vol] = pd.to_numeric(w[mk.vol], errors="coerce").fillna(0)
    w[mk.yds] = pd.to_numeric(w[mk.yds], errors="coerce").fillna(0)
    w = w[w[mk.vol] >= mk.min_vol]
    name_col = "player_display_name" if "player_display_name" in w else "player_name"
    w["name"] = w[name_col]
    return w.sort_values(["player_id", "season", "week"]).reset_index(drop=True)


def player_baselines(hist: pd.DataFrame, mk: Market, season: int, week: int) -> pd.DataFrame:
    """Per player, using games strictly before (season, week): naive L3 (this season only) and the l3_v1 inputs."""
    h = hist[(hist.season < season) | ((hist.season == season) & (hist.week < week))]
    h = h[h.season >= season - 1]
    cur = h[h.season == season]
    prev = h[h.season == season - 1]
    out = []
    for pid, g in h.groupby("player_id"):
        c = cur[cur.player_id == pid]
        pv = prev[prev.player_id == pid]
        last3_any = g.tail(3)                      # rolling L3 across the season boundary for the v1 baseline
        l3c = c.tail(3)                            # naive: this season's last 3 games
        r = {"player_id": pid, "name": g.name.iloc[-1], "team": g.team.iloc[-1], "position": g.position.iloc[-1],
             "naive_n": int(len(l3c)), "naive_l3": float(l3c[mk.yds].mean()) if len(l3c) else float("nan"),
             "naive_games": ",".join(str(int(x)) for x in l3c[mk.yds]),
             "vol_l3": float(last3_any[mk.vol].mean()), "rate_l3": _ratio(last3_any, mk),
             "vol_season": float(c[mk.vol].mean()) if len(c) else float("nan"), "rate_season": _ratio(c, mk) if len(c) else float("nan"),
             "rate_prev": _ratio(pv, mk) if len(pv) and pv[mk.vol].sum() >= 50 else float("nan"),
             "n_season": int(len(c)), "last_week": int(g.week.iloc[-1]), "last_season": int(g.season.iloc[-1])}
        out.append(r)
    return pd.DataFrame(out)


def _ratio(g: pd.DataFrame, mk: Market) -> float:
    v = g[mk.vol].sum()
    return float(g[mk.yds].sum() / v) if v > 0 else float("nan")


# =============================================================== game context
def game_context(games: pd.DataFrame) -> pd.DataFrame:
    """Per (game_id, team): implied team total and the team's spread (negative = favourite), dome, high wind.
    nflverse spread_line is the home team's expected margin (positive = home favoured)."""
    g = games.copy()
    rows = []
    for _, r in g.iterrows():
        sp, tot = r.get("spread_line"), r.get("total_line")
        sp = float(sp) if pd.notna(sp) else 0.0
        tot = float(tot) if pd.notna(tot) else 44.0
        roof = str(r.get("roof") or "")
        dome = roof in ("dome", "closed")
        wind = r.get("wind")
        wind_hi = bool(pd.notna(wind) and float(wind) >= 15 and not dome)
        for team, opp, home in ((r.home_team, r.away_team, True), (r.away_team, r.home_team, False)):
            implied = tot / 2 + (sp / 2 if home else -sp / 2)
            rows.append({"game_id": r.game_id, "season": int(r.season), "week": int(r.week), "team": team, "opp": opp,
                         "home": home, "implied": implied, "team_spread": -sp if home else sp, "total": tot,
                         "dome": dome, "wind_hi": wind_hi, "wind": None if pd.isna(wind) else float(wind),
                         "kickoff_utc": r.get("kickoff_utc")})
    return pd.DataFrame(rows)


# =============================================================== l3_v1 projection model
RATE_FEATS = ["rate_l3", "rate_season", "rate_prev", "def_dev", "wind_hi", "dome"]
VOL_FEATS = ["vol_l3", "vol_season", "implied", "team_spread"]


@dataclass
class Projector:
    market: str
    rate_coef: np.ndarray = None
    rate_icpt: float = 0.0
    vol_coef: np.ndarray = None
    vol_icpt: float = 0.0
    fill: dict = field(default_factory=dict)
    ratio_q: np.ndarray = None            # empirical quantiles of actual / projection (training residuals)
    n_train: int = 0
    trained_through: int = 0

    def _X(self, df: pd.DataFrame, feats: list[str]) -> np.ndarray:
        X = df[feats].astype(float).copy()
        for c in feats:
            X[c] = X[c].fillna(self.fill.get(c, 0.0))
        return X.values

    def fit(self, rows: pd.DataFrame, mk: Market) -> "Projector":
        from sklearn.linear_model import LinearRegression
        r = rows[rows.actual_vol >= mk.train_min_vol].copy()
        self.fill = {c: float(r[c].astype(float).mean()) for c in set(RATE_FEATS + VOL_FEATS)}
        self.fill["rate_season"] = self.fill["rate_l3"]
        self.fill["rate_prev"] = self.fill["rate_l3"]
        self.fill["vol_season"] = self.fill["vol_l3"]
        y_rate = r.actual_yds / r.actual_vol
        lr = LinearRegression().fit(self._X(r, RATE_FEATS), y_rate, sample_weight=r.actual_vol)
        self.rate_coef, self.rate_icpt = lr.coef_, float(lr.intercept_)
        lv = LinearRegression().fit(self._X(r, VOL_FEATS), r.actual_vol)
        self.vol_coef, self.vol_icpt = lv.coef_, float(lv.intercept_)
        proj = self.project(r)
        ratio = (r.actual_yds / proj.clip(lower=1)).clip(-1, 5)
        self.ratio_q = np.quantile(ratio, np.linspace(0, 1, 201))
        self.n_train = int(len(r))
        self.trained_through = int(r.season.max())
        return self

    def project(self, df: pd.DataFrame) -> pd.Series:
        rate = self._X(df, RATE_FEATS) @ self.rate_coef + self.rate_icpt
        vol = np.clip(self._X(df, VOL_FEATS) @ self.vol_coef + self.vol_icpt, 1, None)
        return pd.Series(rate * vol, index=df.index)

    def p_over(self, proj: np.ndarray, line: np.ndarray) -> np.ndarray:
        """P(actual > line) = P(ratio > line/proj) from the empirical ratio CDF."""
        proj = np.asarray(proj, float); line = np.asarray(line, float)
        thr = line / np.clip(proj, 1, None)
        cdf = np.interp(thr, self.ratio_q, np.linspace(0, 1, len(self.ratio_q)))
        return np.clip(1 - cdf, 0.001, 0.999)

    def quantiles(self, proj: float, qs=(0.25, 0.5, 0.75)) -> list[float]:
        return [float(proj * np.interp(q, np.linspace(0, 1, len(self.ratio_q)), self.ratio_q)) for q in qs]

    def to_json(self) -> dict:
        return {"market": self.market, "rate_coef": list(map(float, self.rate_coef)), "rate_icpt": self.rate_icpt,
                "vol_coef": list(map(float, self.vol_coef)), "vol_icpt": self.vol_icpt, "fill": self.fill,
                "ratio_q": list(map(float, self.ratio_q)), "n_train": self.n_train, "trained_through": self.trained_through,
                "rate_feats": RATE_FEATS, "vol_feats": VOL_FEATS}

    @classmethod
    def from_json(cls, d: dict) -> "Projector":
        return cls(d["market"], np.array(d["rate_coef"]), d["rate_icpt"], np.array(d["vol_coef"]), d["vol_icpt"],
                   d["fill"], np.array(d["ratio_q"]), d["n_train"], d["trained_through"])


def feature_rows(hist: pd.DataFrame, tg: pd.DataFrame, ctx: pd.DataFrame, mk: Market, season: int, week: int,
                 params: dict | None = None, dtab: pd.DataFrame | None = None) -> pd.DataFrame:
    """One row per player with history for (season, week): baselines + context + the opponent's shrunk L3.
    Joins the player's team to this week's game; players without a game this week are dropped."""
    b = player_baselines(hist, mk, season, week)
    if b.empty:
        return b
    wk = ctx[(ctx.season == season) & (ctx.week == week)]
    b = b.merge(wk, on="team", how="inner")
    dtab = dtab if dtab is not None else defense_table(tg, season, week, params)
    if dtab.empty:
        return pd.DataFrame()
    side = MARKET_SIDE[mk.key]; s = PRIMARY[side]
    d = dtab[["team", f"{s}_shrunk", f"{s}_sd", f"{s}_z", f"{side}_v1_cond", f"{side}_naive_cond", f"{side}_naive_rank",
              f"{side}_ypg_l3", f"{s}_raw", f"{s}_adj", f"{s}_shrink", "l3_games"]].rename(columns={
        "team": "opp", f"{s}_shrunk": "def_dev", f"{s}_sd": "def_sd", f"{s}_z": "def_z", f"{side}_v1_cond": "v1_cond",
        f"{side}_naive_cond": "naive_cond", f"{side}_naive_rank": "naive_rank", f"{side}_ypg_l3": "def_ypg_l3",
        f"{s}_raw": "def_raw", f"{s}_adj": "def_adj", f"{s}_shrink": "def_shrink", "l3_games": "def_l3_games"})
    return b.merge(d, on="opp", how="left")


# =============================================================== verdicts
def naive_verdict(line: float, l3: float, n: int, cond: str) -> str | None:
    if n < NAIVE_MIN_GAMES or l3 != l3 or line is None:
        return None
    if line < l3 and cond == "soft":
        return "Over"
    if line > l3 and cond == "stingy":
        return "Under"
    return None


INJURY_FLAGGED = ("Questionable", "Doubtful", "Out")


def rb1_only(df: pd.DataFrame) -> pd.DataFrame:
    """Rushing props: keep each team's RB1 per game = the RB with the highest posted rushing line (the book's view of
    the lead back). Backups with 10–30 yd lines are not what the rule is about (DECISIONS #48)."""
    if df.empty:
        return df
    return df.sort_values("line", ascending=False).drop_duplicates(["game_id", "team"]).sort_index()


def naive_gap(line: float, l3: float) -> float:
    """(player L3 − line) / line: +0.30 = he has averaged 30% more than the line."""
    if line is None or l3 != l3 or not line:
        return float("nan")
    return (l3 - line) / line


def naive_g10_verdict(line: float, l3: float, n: int, cond: str) -> str | None:
    """naive_v0 plus a size gate: the L3-vs-line gap must be at least NAIVE_GATE of the line, in the flag's direction."""
    side = naive_verdict(line, l3, n, cond)
    g = naive_gap(line, l3)
    return side if side and abs(g) >= NAIVE_GATE else None


def v1_verdict(p_over: float, fair_over: float, cond: str) -> tuple[str | None, float]:
    """Direction comes from the defense condition; the projection has to agree by ≥ V1_MIN_EDGE vs the no-vig price."""
    if cond == "soft":
        e = p_over - fair_over
        return ("Over" if e >= V1_MIN_EDGE else None), e
    if cond == "stingy":
        e = (1 - p_over) - (1 - fair_over)
        return ("Under" if e >= V1_MIN_EDGE else None), e
    return None, float("nan")


# =============================================================== stats helpers for the ledger / backtest
def summarize_bets(b: pd.DataFrame) -> dict:
    """W-L-P, hit rate, ROI with a 95% CI and t-stat on per-bet profit (1u flat)."""
    b = b[b.result.isin(["win", "loss", "push"])]
    n = len(b)
    if n == 0:
        return {"n": 0, "w": 0, "l": 0, "p": 0, "hit": None, "roi": None, "units": 0.0, "ci_lo": None, "ci_hi": None, "t": None}
    pnl = b.pnl.astype(float).values
    w, l, p = int((b.result == "win").sum()), int((b.result == "loss").sum()), int((b.result == "push").sum())
    m = float(pnl.mean()); se = float(pnl.std(ddof=1) / math.sqrt(n)) if n > 1 else float("nan")
    return {"n": n, "w": w, "l": l, "p": p, "hit": w / max(w + l, 1), "roi": m, "units": float(pnl.sum()),
            "ci_lo": m - 1.96 * se if se == se else None, "ci_hi": m + 1.96 * se if se == se else None,
            "t": m / se if se and se == se else None}


def lean_eligible(summary: dict) -> bool:
    return bool(summary.get("n", 0) >= LEAN_MIN_BETS and summary.get("ci_lo") is not None and summary["ci_lo"] > LEAN_MIN_CI_LO)
