export const TEAM_NAMES: Record<string, string> = {
  ARI: "Cardinals", ATL: "Falcons", BAL: "Ravens", BUF: "Bills", CAR: "Panthers", CHI: "Bears", CIN: "Bengals",
  CLE: "Browns", DAL: "Cowboys", DEN: "Broncos", DET: "Lions", GB: "Packers", HOU: "Texans", IND: "Colts",
  JAX: "Jaguars", KC: "Chiefs", LV: "Raiders", LAC: "Chargers", LA: "Rams", MIA: "Dolphins", MIN: "Vikings",
  NE: "Patriots", NO: "Saints", NYG: "Giants", NYJ: "Jets", PHI: "Eagles", PIT: "Steelers", SF: "49ers",
  SEA: "Seahawks", TB: "Buccaneers", TEN: "Titans", WAS: "Commanders",
};
export const BOOK_NAMES: Record<string, string> = {
  draftkings: "DraftKings", fanduel: "FanDuel", betmgm: "BetMGM", betrivers: "BetRivers", bovada: "Bovada",
  betonlineag: "BetOnline", williamhill_us: "Caesars", pointsbetus: "PointsBet", unibet_us: "Unibet",
  fanatics: "Fanatics", polymarket: "Polymarket", lowvig: "LowVig", mybookieag: "MyBookie", espnbet: "ESPN BET", ballybet: "Bally Bet", betparx: "betPARX", hardrockbet: "Hard Rock", betus: "BetUS", pinnacle: "Pinnacle",
};
export const MARKET_NAMES: Record<string, string> = {
  player_pass_yds: "Passing Yards", player_reception_yds: "Receiving Yards", player_rush_yds: "Rushing Yards",
  player_receptions: "Receptions", player_pass_tds: "Passing TDs", player_anytime_td: "Anytime TD", h2h: "Moneyline",
};
export const american = (n: number) => (n > 0 ? `+${n}` : `${n}`);
export const pct = (p: number, d = 0) => `${(p * 100).toFixed(d)}%`;
export const signedPct = (p: number, d = 1) => `${p >= 0 ? "+" : ""}${(p * 100).toFixed(d)}%`;
export const book = (k: string) => BOOK_NAMES[k] ?? k;
export const kickoff = (iso: string | Date) =>
  new Date(iso).toLocaleString("en-US", { weekday: "short", hour: "numeric", minute: "2-digit", timeZone: "America/New_York" }) + " ET";
export const ago = (iso: string | Date) => {
  const m = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  if (h < 48) return `${h}h ago`;
  return `${Math.round(h / 24)}d ago`;
};
export const num = (n: number | string | null | undefined, d = 1) => (n == null ? "–" : Number(n).toFixed(d));
