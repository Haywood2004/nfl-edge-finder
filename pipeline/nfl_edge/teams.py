"""Team name normalization. nflverse abbreviations are canonical."""
ODDS_API_TO_ABBR = {
    "Arizona Cardinals": "ARI", "Atlanta Falcons": "ATL", "Baltimore Ravens": "BAL", "Buffalo Bills": "BUF",
    "Carolina Panthers": "CAR", "Chicago Bears": "CHI", "Cincinnati Bengals": "CIN", "Cleveland Browns": "CLE",
    "Dallas Cowboys": "DAL", "Denver Broncos": "DEN", "Detroit Lions": "DET", "Green Bay Packers": "GB",
    "Houston Texans": "HOU", "Indianapolis Colts": "IND", "Jacksonville Jaguars": "JAX", "Kansas City Chiefs": "KC",
    "Las Vegas Raiders": "LV", "Los Angeles Chargers": "LAC", "Los Angeles Rams": "LA", "Miami Dolphins": "MIA",
    "Minnesota Vikings": "MIN", "New England Patriots": "NE", "New Orleans Saints": "NO", "New York Giants": "NYG",
    "New York Jets": "NYJ", "Philadelphia Eagles": "PHI", "Pittsburgh Steelers": "PIT", "San Francisco 49ers": "SF",
    "Seattle Seahawks": "SEA", "Tampa Bay Buccaneers": "TB", "Tennessee Titans": "TEN", "Washington Commanders": "WAS",
}
ABBR_TO_NAME = {v: k for k, v in ODDS_API_TO_ABBR.items()}
# Historical relocations in nflverse data → current abbr
LEGACY = {"OAK": "LV", "SD": "LAC", "STL": "LA"}

# Stadium coordinates for Open-Meteo, roof from nflverse where available.
STADIUMS = {
    "ARI": ("State Farm Stadium", 33.5276, -112.2626, "retractable", "America/Phoenix"),
    "ATL": ("Mercedes-Benz Stadium", 33.7554, -84.4010, "retractable", "America/New_York"),
    "BAL": ("M&T Bank Stadium", 39.2780, -76.6227, "outdoors", "America/New_York"),
    "BUF": ("Highmark Stadium", 42.7738, -78.7870, "outdoors", "America/New_York"),
    "CAR": ("Bank of America Stadium", 35.2258, -80.8528, "outdoors", "America/New_York"),
    "CHI": ("Soldier Field", 41.8623, -87.6167, "outdoors", "America/Chicago"),
    "CIN": ("Paycor Stadium", 39.0954, -84.5160, "outdoors", "America/New_York"),
    "CLE": ("Huntington Bank Field", 41.5061, -81.6995, "outdoors", "America/New_York"),
    "DAL": ("AT&T Stadium", 32.7473, -97.0945, "retractable", "America/Chicago"),
    "DEN": ("Empower Field at Mile High", 39.7439, -105.0201, "outdoors", "America/Denver"),
    "DET": ("Ford Field", 42.3400, -83.0456, "dome", "America/Detroit"),
    "GB": ("Lambeau Field", 44.5013, -88.0622, "outdoors", "America/Chicago"),
    "HOU": ("NRG Stadium", 29.6847, -95.4107, "retractable", "America/Chicago"),
    "IND": ("Lucas Oil Stadium", 39.7601, -86.1639, "retractable", "America/Indiana/Indianapolis"),
    "JAX": ("EverBank Stadium", 30.3239, -81.6373, "outdoors", "America/New_York"),
    "KC": ("GEHA Field at Arrowhead", 39.0489, -94.4839, "outdoors", "America/Chicago"),
    "LV": ("Allegiant Stadium", 36.0909, -115.1833, "dome", "America/Los_Angeles"),
    "LAC": ("SoFi Stadium", 33.9535, -118.3392, "dome", "America/Los_Angeles"),
    "LA": ("SoFi Stadium", 33.9535, -118.3392, "dome", "America/Los_Angeles"),
    "MIA": ("Hard Rock Stadium", 25.9580, -80.2389, "outdoors", "America/New_York"),
    "MIN": ("U.S. Bank Stadium", 44.9736, -93.2575, "dome", "America/Chicago"),
    "NE": ("Gillette Stadium", 42.0909, -71.2643, "outdoors", "America/New_York"),
    "NO": ("Caesars Superdome", 29.9511, -90.0812, "dome", "America/Chicago"),
    "NYG": ("MetLife Stadium", 40.8135, -74.0745, "outdoors", "America/New_York"),
    "NYJ": ("MetLife Stadium", 40.8135, -74.0745, "outdoors", "America/New_York"),
    "PHI": ("Lincoln Financial Field", 39.9008, -75.1675, "outdoors", "America/New_York"),
    "PIT": ("Acrisure Stadium", 40.4468, -80.0158, "outdoors", "America/New_York"),
    "SF": ("Levi's Stadium", 37.4033, -121.9694, "outdoors", "America/Los_Angeles"),
    "SEA": ("Lumen Field", 47.5952, -122.3316, "outdoors", "America/Los_Angeles"),
    "TB": ("Raymond James Stadium", 27.9759, -82.5033, "outdoors", "America/New_York"),
    "TEN": ("Nissan Stadium", 36.1665, -86.7713, "outdoors", "America/Chicago"),
    "WAS": ("Northwest Stadium", 38.9076, -76.8645, "outdoors", "America/New_York"),
}


def norm(abbr: str) -> str:
    return LEGACY.get(abbr, abbr)
