"""Builds engine/dd_classics/*.json from the curated, hand-verified banks below.

Run: ~/Desktop/fantasy-app/.venv/bin/python analysis/build_classics.py

Each bank lists answers MOST POPULAR FIRST. Unless an explicit tier is given as the 4th tuple item, the tier comes from the
rank in that list through the same percentile cut-offs the data-driven pools use (dd.tier_for_rank: top 20% tier 1 ...
last 10% tier 6). So tiers are editorial (our judgement of what a fan names first), not computed from stats.
Every fact below was checked against at least two sources (see SRC); the URLs are written into each answer.
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from engine import daily_drive as dd  # noqa: E402

OUT = os.path.join(ROOT, "engine", "dd_classics")
VERSION = 1

W = "https://en.wikipedia.org/wiki/"
SRC = {
    "sb_champs": W + "List_of_Super_Bowl_champions",
    "sb_qbs": W + "List_of_Super_Bowl_starting_quarterbacks",
    "sb_qbs_hof": "https://www.profootballhof.com/news/super-bowl-starting-qbs",
    "sb_mvp": W + "Super_Bowl_Most_Valuable_Player_Award",
    "sb_mvp2": "https://www.cbssports.com/nfl/news/super-bowl-results-winners-mvps-history-full-list/",
    "sb_coaches": W + "List_of_Super_Bowl_head_coaches",
    "sb_coaches2": "https://en.wikipedia.org/wiki/Category:Super_Bowl%E2%80%93winning_head_coaches",
    "stadiums": W + "List_of_current_NFL_stadiums",
    "stadiums2": "https://sportsfoundation.org/nfl-teams-map/",
    "stadium_chron": W + "Chronology_of_home_stadiums_for_current_NFL_teams",
    "mascots": W + "List_of_NFL_mascots",
    "mascots2": "https://sportmascots.com/nfl/",
    "draft1": W + "List_of_first_overall_NFL_draft_picks",
    "draft2": "https://www.espn.ph/nfl/story/_/id/39958676/no-1-nfl-draft-picks-history-know",
    "mvp": "https://apnews.com/article/ap-nfl-mvp-f0c84ba614bcd6c3d17ec53c04451046",
    "mvp2": W + "AP_NFL_Most_Valuable_Player",
    "dpoy": "https://apnews.com/article/nfl-defensive-player-award-bb30011685df181fe2db6342ad8c9768",
    "dpoy2": "https://www.pro-football-reference.com/awards/ap-defensive-player-of-the-year.htm",
    "opoy": "https://apnews.com/article/nfl-offensive-player-award-b200f07d5750a45dd33f78fddf9cfe28",
    "opoy2": W + "AP_NFL_Offensive_Player_of_the_Year",
    "oroy": "https://apnews.com/article/nfl-offensive-rookie-list-047a8b29a925336a4c92d7172c25ef46",
    "oroy2": "https://eatdrinkandsleepfootball.com/history/awards/offroy.html",
    "droy": W + "AP_NFL_Rookie_of_the_Year",
    "droy2": "https://www.footballdb.com/awards/ap-nfl-defensive-rookie-of-the-year",
    "nfl_honors": "https://www.nfl.com/news/list-of-nfl-honors-award-winners-from-2025-nfl-season",
    "sacks": "https://www.pro-football-reference.com/leaders/sacks_career.htm",
    "sacks2": W + "List_of_NFL_career_sacks_leaders",
    "rush": W + "List_of_NFL_career_rushing_yards_leaders",
    "rush2": "https://www.profootballhof.com/top-20-rushing-yards",
    "rec": "https://www.pro-football-reference.com/leaders/rec_yds_career.htm",
    "rec2": "https://www.pro-football-reference.com/leaders/rec_yds_career_2016.htm",
    "pass": "https://www.pro-football-reference.com/leaders/pass_yds_career.htm",
    "pass2": "https://www.profootballhof.com/top-20-passing-yards",
    "fg": "https://www.pro-football-reference.com/leaders/fgm_career.htm",
    "fg2": W + "List_of_most_career_field_goals_in_NFL_history",
    "hof_pos": "https://www.profootballhof.com/hall-of-famers/positions",
    "hof_wiki": W + "List_of_Pro_Football_Hall_of_Fame_inductees",
    "hof_2026": "https://en.as.com/nfl/who-made-the-pro-football-hall-of-fame-class-of-2026-full-list-of-inductees-f202608-n/",
    "franchise_hof": "https://www.profootballhof.com/football-history/national-footbal-league-franchise-histories",
    "defunct": W + "List_of_defunct_NFL_teams",
    "defunct2": "https://www.jt-sw.com/football/pro/teams.nsf/PastTeams?OpenPage",
}


def slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def build_answers(rows, src, sources_all):
    """rows: (name, aliases, note[, tier]) most popular first."""
    n = len(rows)
    out, seen = [], set()
    for i, r in enumerate(rows):
        name, aliases, note = r[0], list(r[1]), r[2]
        tier = r[3] if len(r) > 3 else dd.tier_for_rank(i, n)
        aid = slug(name)
        assert aid not in seen, f"duplicate answer {name}"
        seen.add(aid)
        out.append({"id": aid, "name": name, "aliases": aliases, "tier": tier, "note": note, "source": src})
    return out


PROMPTS = []


def P(key, cat, text, era, group, sources, rows, answer_source=None):
    PROMPTS.append(dict(key=key, cat=cat, text=text, era=era, group=group, sources=[SRC[s] for s in sources],
                        rows=rows, src=SRC[answer_source or sources[0]]))


# ============================================================================================= team table
# (full name, aliases, short). Aliases are other names the same franchise has used or fans type.
T = {
    "DAL": ("Dallas Cowboys", ["Dallas", "Cowboys", "Americas Team"]),
    "NE": ("New England Patriots", ["New England", "Patriots", "Boston Patriots", "Pats"]),
    "GB": ("Green Bay Packers", ["Green Bay", "Packers"]),
    "KC": ("Kansas City Chiefs", ["Kansas City", "Chiefs"]),
    "PIT": ("Pittsburgh Steelers", ["Pittsburgh", "Steelers", "Pittsburgh Pirates"]),
    "SF": ("San Francisco 49ers", ["San Francisco", "49ers", "Niners", "SF 49ers", "Forty Niners"]),
    "PHI": ("Philadelphia Eagles", ["Philadelphia", "Eagles"]),
    "CHI": ("Chicago Bears", ["Chicago", "Bears", "Decatur Staleys", "Chicago Staleys", "Staleys"]),
    "NYG": ("New York Giants", ["Giants", "NY Giants"]),
    "LV": ("Las Vegas Raiders", ["Raiders", "LV Raiders", "Oakland Raiders", "Los Angeles Raiders", "LA Raiders", "Vegas Raiders"]),
    "DEN": ("Denver Broncos", ["Denver", "Broncos"]),
    "SEA": ("Seattle Seahawks", ["Seattle", "Seahawks"]),
    "BUF": ("Buffalo Bills", ["Buffalo", "Bills"]),
    "BAL": ("Baltimore Ravens", ["Baltimore", "Ravens"]),
    "MIA": ("Miami Dolphins", ["Miami", "Dolphins"]),
    "LAR": ("Los Angeles Rams", ["Rams", "LA Rams", "St. Louis Rams", "Saint Louis Rams", "Cleveland Rams"]),
    "MIN": ("Minnesota Vikings", ["Minnesota", "Vikings"]),
    "DET": ("Detroit Lions", ["Detroit", "Lions", "Portsmouth Spartans"]),
    "NYJ": ("New York Jets", ["Jets", "NY Jets", "New York Titans"]),
    "IND": ("Indianapolis Colts", ["Indianapolis", "Colts", "Baltimore Colts"]),
    "TB": ("Tampa Bay Buccaneers", ["Tampa Bay", "Buccaneers", "Bucs", "Tampa"]),
    "NO": ("New Orleans Saints", ["New Orleans", "Saints"]),
    "LAC": ("Los Angeles Chargers", ["Chargers", "LA Chargers", "San Diego Chargers"]),
    "CLE": ("Cleveland Browns", ["Cleveland", "Browns"]),
    "CIN": ("Cincinnati Bengals", ["Cincinnati", "Bengals"]),
    "ATL": ("Atlanta Falcons", ["Atlanta", "Falcons"]),
    "CAR": ("Carolina Panthers", ["Carolina", "Panthers"]),
    "ARI": ("Arizona Cardinals", ["Arizona", "Cardinals", "Phoenix Cardinals", "St. Louis Cardinals", "Chicago Cardinals", "Cards"]),
    "TEN": ("Tennessee Titans", ["Tennessee", "Titans", "Houston Oilers", "Tennessee Oilers", "Oilers"]),
    "JAX": ("Jacksonville Jaguars", ["Jacksonville", "Jaguars", "Jags"]),
    "HOU": ("Houston Texans", ["Houston", "Texans"]),
    "WAS": ("Washington Commanders", ["Washington", "Commanders", "Redskins", "Washington Redskins", "Football Team", "Washington Football Team", "Boston Braves", "Boston Redskins"]),
}


def teams(*shorts):
    return [(T[s][0], T[s][1], None) for s in shorts]


def team_rows(shorts, notes):
    return [(T[s][0], T[s][1], notes.get(s) or notes.get("*", "")) for s in shorts]


# ============================================================================================= 1. franchise
cur = [  # tier set explicitly: 8 / 8 / 8 / 8 across tiers 1-4
    ("DAL", 1), ("NE", 1), ("GB", 1), ("KC", 1), ("PIT", 1), ("SF", 1), ("PHI", 1), ("CHI", 1),
    ("NYG", 2), ("LV", 2), ("DEN", 2), ("SEA", 2), ("BUF", 2), ("BAL", 2), ("MIA", 2), ("LAR", 2),
    ("MIN", 3), ("DET", 3), ("NYJ", 3), ("IND", 3), ("TB", 3), ("NO", 3), ("LAC", 3), ("CLE", 3),
    ("CIN", 4), ("ATL", 4), ("CAR", 4), ("ARI", 4), ("TEN", 4), ("JAX", 4), ("HOU", 4), ("WAS", 4),
]
franchise_rows = [(T[s][0], T[s][1], "Current NFL franchise (also answers to its former names)", t) for s, t in cur]
defunct = [  # (name, aliases, years, tier). Names/years: Pro Football HOF franchise histories + Wikipedia defunct list.
    ("Canton Bulldogs", ["Canton"], "1920-1926", 5),
    ("Boston Yanks", ["Yanks"], "1944-1948", 5),
    ("Brooklyn Dodgers", ["Brooklyn Tigers"], "1930-1944", 5),
    ("Duluth Eskimos", ["Duluth Kelleys", "Eskimos", "Duluth"], "1923-1927", 5),
    ("Pottsville Maroons", ["Boston Bulldogs", "Pottsville"], "1925-1928 (moved to Boston in 1929)", 5),
    ("Providence Steam Roller", ["Providence Steamroller", "Steam Roller", "Steamroller", "Providence"], "1925-1931", 5),
    ("Frankford Yellow Jackets", ["Frankford Yellowjackets", "Yellow Jackets", "Yellowjackets"], "1924-1931", 5),
    ("Dayton Triangles", ["Triangles", "Dayton"], "1920-1929", 6),
    ("Akron Pros", ["Akron Indians", "Akron"], "1920-1926", 6),
    ("Rock Island Independents", ["Independents", "Rock Island"], "1920-1925", 6),
    ("Hammond Pros", ["Hammond"], "1920-1926", 6),
    ("Muncie Flyers", ["Flyers", "Muncie"], "1920-1921", 6),
    ("Milwaukee Badgers", ["Badgers", "Milwaukee"], "1922-1926", 6),
    ("Racine Legion", ["Racine Tornadoes", "Racine"], "1922-1926", 6),
    ("Rochester Jeffersons", ["Jeffersons", "Rochester"], "1920-1925", 6),
    ("Evansville Crimson Giants", ["Crimson Giants", "Evansville"], "1921-1922", 6),
    ("Oorang Indians", ["Oorang"], "1922-1923", 6),
    ("Staten Island Stapletons", ["Stapletons", "Staten Island Stapes", "Stapes"], "1929-1932", 6),
    ("Orange Tornadoes", ["Newark Tornadoes"], "1929-1930 (Orange, then Newark)", 6),
    ("Louisville Colonels", ["Louisville Brecks", "Louisville Breckenridges", "Brecks"], "1921-1923, 1926", 6),
    ("Columbus Panhandles", ["Columbus Tigers", "Panhandles"], "1920-1926", 6),
    ("Toledo Maroons", ["Toledo"], "1922-1923", 6),
    ("Kenosha Maroons", ["Kenosha"], "1924", 6),
    ("Hartford Blues", ["Hartford"], "1926", 6),
    ("Cincinnati Reds", ["Reds"], "1933-1934", 6),
    ("St. Louis Gunners", ["Saint Louis Gunners", "Gunners"], "1934", 6),
    ("Minneapolis Marines", ["Minneapolis Red Jackets", "Minneapolis Redjackets", "Marines"], "1921-1924, 1929-1930", 6),
    ("Buffalo All-Americans", ["Buffalo Bisons", "Buffalo Rangers", "All-Americans"], "1920-1929", 6),
    ("Cleveland Bulldogs", ["Cleveland Indians"], "1923-1927 (Indians, then Bulldogs)", 6),
    ("Detroit Wolverines", ["Wolverines"], "1928", 6),
    ("Tonawanda Kardex", ["Kardex", "Tonawanda"], "1921", 6),
    ("New York Yankees", ["Yankees"], "1927-1928", 6),
    ("Cincinnati Celts", ["Celts"], "1921", 6),
    ("Washington Senators", ["Senators"], "1921", 6),
]
franchise_rows += [(n, a, f"Defunct NFL franchise, {y}", t) for n, a, y, t in defunct]
P("nfl-franchise", "NFL franchises", "Name an NFL franchise", "all", "franchise",
  ["franchise_hof", "defunct", "defunct2"], franchise_rows, "franchise_hof")

# ============================================================================================= Super Bowl (2000+)
P("sb-winning-qb-2000", "Super Bowl", "Name a quarterback who has won a Super Bowl since the 2000 season", "2000+", "sb-qb",
  ["sb_qbs", "sb_qbs_hof", "sb_champs"], [
    ("Tom Brady", ["Brady"], "7 titles (XXXVI, XXXVIII, XXXIX, XLIX, LI, LIII, LV)"),
    ("Patrick Mahomes", ["Mahomes"], "LIV, LVII, LVIII"),
    ("Peyton Manning", ["Peyton"], "XLI (Colts) and 50 (Broncos)"),
    ("Eli Manning", ["Eli"], "XLII and XLVI (Giants)"),
    ("Aaron Rodgers", ["Rodgers"], "XLV (Packers)"),
    ("Drew Brees", ["Brees"], "XLIV (Saints)"),
    ("Ben Roethlisberger", ["Big Ben", "Roethlisberger"], "XL and XLIII (Steelers)"),
    ("Russell Wilson", ["Wilson"], "XLVIII (Seahawks)"),
    ("Matthew Stafford", ["Matt Stafford"], "LVI (Rams)"),
    ("Jalen Hurts", ["Hurts"], "LIX (Eagles)"),
    ("Joe Flacco", ["Flacco"], "XLVII (Ravens)"),
    ("Nick Foles", ["Foles"], "LII (Eagles)"),
    ("Sam Darnold", ["Darnold"], "LX (Seahawks)"),
    ("Brad Johnson", [], "XXXVII (Buccaneers)"),
    ("Trent Dilfer", ["Dilfer"], "XXXV (Ravens)"),
])

P("sb-starting-qb-2000", "Super Bowl", "Name a quarterback who has started a Super Bowl since the 2000 season", "2000+", "sb-qb",
  ["sb_qbs", "sb_qbs_hof"], [
    ("Tom Brady", ["Brady"], "10 Super Bowl starts"),
    ("Patrick Mahomes", ["Mahomes"], "5 starts"),
    ("Peyton Manning", ["Peyton"], "XLI, XLIV, XLVIII, 50"),
    ("Eli Manning", ["Eli"], "XLII, XLVI"),
    ("Aaron Rodgers", ["Rodgers"], "XLV"),
    ("Drew Brees", ["Brees"], "XLIV"),
    ("Ben Roethlisberger", ["Big Ben", "Roethlisberger"], "XL, XLIII, XLV"),
    ("Russell Wilson", ["Wilson"], "XLVIII, XLIX"),
    ("Matthew Stafford", ["Matt Stafford"], "LVI"),
    ("Jalen Hurts", ["Hurts"], "LVII, LIX"),
    ("Joe Burrow", ["Burrow"], "LVI (Bengals)"),
    ("Cam Newton", ["Newton"], "50 (Panthers)"),
    ("Colin Kaepernick", ["Kaepernick", "Kap"], "XLVII (49ers)"),
    ("Matt Ryan", ["Ryan"], "LI (Falcons)"),
    ("Brock Purdy", ["Purdy"], "LVIII (49ers)"),
    ("Jared Goff", ["Goff"], "LIII (Rams)"),
    ("Kurt Warner", ["Warner"], "XXXVI (Rams), XLIII (Cardinals)"),
    ("Donovan McNabb", ["McNabb"], "XXXIX (Eagles)"),
    ("Joe Flacco", ["Flacco"], "XLVII"),
    ("Nick Foles", ["Foles"], "LII"),
    ("Jimmy Garoppolo", ["Garoppolo", "Jimmy G"], "LIV (49ers)"),
    ("Sam Darnold", ["Darnold"], "LX (Seahawks)"),
    ("Drake Maye", ["Maye"], "LX (Patriots)"),
    ("Matt Hasselbeck", ["Hasselbeck"], "XL (Seahawks)"),
    ("Rich Gannon", ["Gannon"], "XXXVII (Raiders)"),
    ("Jake Delhomme", ["Delhomme"], "XXXVIII (Panthers)"),
    ("Kerry Collins", ["Collins"], "XXXV (Giants)"),
    ("Rex Grossman", ["Grossman"], "XLI (Bears)"),
    ("Brad Johnson", [], "XXXVII (Buccaneers)"),
    ("Trent Dilfer", ["Dilfer"], "XXXV (Ravens)"),
])

P("sb-mvp-2000", "Super Bowl", "Name a Super Bowl MVP since the 2000 season", "2000+", "sb-mvp",
  ["sb_mvp", "sb_mvp2", "nfl_honors"], [
    ("Tom Brady", ["Brady"], "5 MVPs: XXXVI, XXXVIII, XLIX, LI, LV"),
    ("Patrick Mahomes", ["Mahomes"], "LIV, LVII, LVIII"),
    ("Eli Manning", ["Eli"], "XLII, XLVI"),
    ("Peyton Manning", ["Peyton"], "XLI"),
    ("Aaron Rodgers", ["Rodgers"], "XLV"),
    ("Drew Brees", ["Brees"], "XLIV"),
    ("Jalen Hurts", ["Hurts"], "LIX"),
    ("Ray Lewis", ["Lewis"], "XXXV (Ravens LB)"),
    ("Von Miller", ["Miller"], "50 (Broncos LB)"),
    ("Julian Edelman", ["Edelman"], "LIII (Patriots WR)"),
    ("Cooper Kupp", ["Kupp"], "LVI (Rams WR)"),
    ("Nick Foles", ["Foles"], "LII (Eagles QB)"),
    ("Joe Flacco", ["Flacco"], "XLVII (Ravens QB)"),
    ("Kenneth Walker III", ["Kenneth Walker", "Ken Walker"], "LX (Seahawks RB)"),
    ("Santonio Holmes", ["Holmes"], "XLIII (Steelers WR)"),
    ("Hines Ward", ["Ward"], "XL (Steelers WR)"),
    ("Malcolm Smith", [], "XLVIII (Seahawks LB)"),
    ("Deion Branch", ["Branch"], "XXXIX (Patriots WR)"),
    ("Dexter Jackson", [], "XXXVII (Buccaneers S)"),
])

P("sb-coach-2000", "Super Bowl", "Name a head coach who has won a Super Bowl since the 2000 season", "2000+", "sb-coach",
  ["sb_coaches", "sb_coaches2"], [
    ("Bill Belichick", ["Belichick"], "6 titles with the Patriots"),
    ("Andy Reid", ["Reid"], "LIV, LVII, LVIII (Chiefs)"),
    ("Mike Tomlin", ["Tomlin"], "XLIII (Steelers)"),
    ("Sean Payton", ["Payton"], "XLIV (Saints)"),
    ("Sean McVay", ["McVay"], "LVI (Rams)"),
    ("Pete Carroll", ["Carroll"], "XLVIII (Seahawks)"),
    ("John Harbaugh", ["Harbaugh"], "XLVII (Ravens)"),
    ("Tom Coughlin", ["Coughlin"], "XLII and XLVI (Giants)"),
    ("Jon Gruden", ["Gruden"], "XXXVII (Buccaneers)"),
    ("Tony Dungy", ["Dungy"], "XLI (Colts)"),
    ("Mike McCarthy", ["McCarthy"], "XLV (Packers)"),
    ("Bruce Arians", ["Arians"], "LV (Buccaneers)"),
    ("Nick Sirianni", ["Sirianni"], "LIX (Eagles)"),
    ("Bill Cowher", ["Cowher"], "XL (Steelers)"),
    ("Doug Pederson", ["Pederson"], "LII (Eagles)"),
    ("Gary Kubiak", ["Kubiak"], "50 (Broncos)"),
    ("Mike Macdonald", ["Macdonald", "Mike McDonald"], "LX (Seahawks)"),
    ("Brian Billick", ["Billick"], "XXXV (Ravens)"),
])

P("sb-stadium-2000", "Super Bowl", "Name a stadium that has hosted a Super Bowl since the 2000 season", "2000+", "sb-venue",
  ["sb_champs", "stadium_chron", "stadiums"], [
    ("AT&T Stadium", ["Cowboys Stadium", "ATT Stadium"], "Super Bowl XLV (2011)"),
    ("SoFi Stadium", ["Sofi"], "Super Bowl LVI (2022)"),
    ("Caesars Superdome", ["Superdome", "Louisiana Superdome", "Mercedes-Benz Superdome", "Mercedes Benz Superdome", "New Orleans Superdome"],
     "Super Bowls XXXVI, XLVII and LIX"),
    ("Raymond James Stadium", ["Ray Jay"], "Super Bowls XXXV, XLIII, LV"),
    ("Hard Rock Stadium", ["Sun Life Stadium", "Dolphin Stadium", "Pro Player Stadium", "Land Shark Stadium", "Joe Robbie Stadium"],
     "Super Bowls XLI and XLIV (as Dolphin / Sun Life) and LIV"),
    ("State Farm Stadium", ["University of Phoenix Stadium", "Univ of Phoenix Stadium", "Phoenix Stadium"], "Super Bowls XLII, XLIX, LVII"),
    ("MetLife Stadium", ["Met Life Stadium"], "Super Bowl XLVIII (2014)"),
    ("Mercedes-Benz Stadium", ["Mercedes Benz Stadium"], "Super Bowl LIII (2019)"),
    ("Levi's Stadium", ["Levis Stadium"], "Super Bowls 50 and LX"),
    ("U.S. Bank Stadium", ["US Bank Stadium"], "Super Bowl LII (2018)"),
    ("Lucas Oil Stadium", [], "Super Bowl XLVI (2012)"),
    ("NRG Stadium", ["Reliant Stadium"], "Super Bowls XXXVIII (as Reliant) and LI"),
    ("Allegiant Stadium", [], "Super Bowl LVIII (2024)"),
    ("Ford Field", [], "Super Bowl XL (2006)"),
    ("Qualcomm Stadium", ["Jack Murphy Stadium", "San Diego Stadium", "SDCCU Stadium"], "Super Bowl XXXVII (2003)"),
    ("EverBank Stadium", ["Alltel Stadium", "Jacksonville Municipal Stadium", "TIAA Bank Field", "EverBank Field"], "Super Bowl XXXIX (2005, as Alltel Stadium)"),
])

P("sb-city-2000", "Super Bowl", "Name a city that has hosted a Super Bowl since the 2000 season", "2000+", "sb-venue",
  ["sb_champs", "sb_mvp2", "stadiums"], [
    ("New Orleans", [], "Super Bowls XXXVI, XLVII, LIX"),
    ("Miami", ["Miami Gardens"], "Super Bowls XLI, XLIV, LIV (Miami Gardens)"),
    ("Tampa", ["Tampa Bay"], "Super Bowls XXXV, XLIII, LV"),
    ("Las Vegas", ["Paradise"], "Super Bowl LVIII (2024)"),
    ("Glendale", ["Phoenix"], "Super Bowls XLII, XLIX, LVII"),
    ("Atlanta", [], "Super Bowl LIII (2019)"),
    ("Houston", [], "Super Bowls XXXVIII and LI"),
    ("Minneapolis", [], "Super Bowl LII (2018)"),
    ("Inglewood", ["Los Angeles"], "Super Bowl LVI (2022)"),
    ("Santa Clara", [], "Super Bowls 50 and LX"),
    ("Arlington", ["Dallas"], "Super Bowl XLV (2011)"),
    ("San Diego", [], "Super Bowl XXXVII (2003)"),
    ("Indianapolis", [], "Super Bowl XLVI (2012)"),
    ("East Rutherford", ["New Jersey", "New York", "NY/NJ"], "Super Bowl XLVIII (2014)"),
    ("Detroit", [], "Super Bowl XL (2006)"),
    ("Jacksonville", [], "Super Bowl XXXIX (2005)"),
])

P("sb-teams-2000", "Super Bowl", "Name a team that has played in a Super Bowl since the 2000 season", "2000+", "sb-team",
  ["sb_champs", "sb_qbs"], team_rows(
    ["NE", "KC", "PHI", "PIT", "NYG", "SEA", "LAR", "SF", "BAL", "GB", "DEN", "IND", "CHI", "NO", "TB", "CAR", "ATL", "CIN", "ARI", "LV"],
    {"*": "Played in at least one Super Bowl from XXXV (2001) through LX (2026)"}))

# ============================================================================================= awards (2000+)
P("nfl-mvp-2000", "NFL awards", "Name a player who has won AP NFL MVP since the 2000 season", "2000+", "mvp",
  ["mvp", "mvp2"], [
    ("Patrick Mahomes", ["Mahomes"], "2018, 2022"),
    ("Tom Brady", ["Brady"], "2007, 2010, 2017"),
    ("Peyton Manning", ["Peyton"], "2003 (co), 2004, 2008, 2009, 2013"),
    ("Aaron Rodgers", ["Rodgers"], "2011, 2014, 2020, 2021"),
    ("Lamar Jackson", ["Lamar"], "2019, 2023"),
    ("Josh Allen", ["Allen"], "2024"),
    ("Cam Newton", ["Newton"], "2015"),
    ("Adrian Peterson", ["AP", "Peterson"], "2012"),
    ("LaDainian Tomlinson", ["LT", "Tomlinson"], "2006"),
    ("Matthew Stafford", ["Matt Stafford"], "2025"),
    ("Matt Ryan", ["Ryan"], "2016"),
    ("Kurt Warner", ["Warner"], "2001"),
    ("Marshall Faulk", ["Faulk"], "2000"),
    ("Shaun Alexander", ["Alexander"], "2005"),
    ("Rich Gannon", ["Gannon"], "2002"),
    ("Steve McNair", ["McNair"], "2003 (co-MVP with Peyton Manning)"),
])

P("nfl-dpoy-2000", "NFL awards", "Name a player who has won AP Defensive Player of the Year since the 2000 season", "2000+", "dpoy",
  ["dpoy", "dpoy2", "nfl_honors"], [
    ("J.J. Watt", ["JJ Watt", "Watt"], "2012, 2014, 2015"),
    ("Aaron Donald", ["Donald"], "2017, 2018, 2020"),
    ("Ray Lewis", ["Lewis"], "2000, 2003"),
    ("Myles Garrett", ["Garrett"], "2023, 2025"),
    ("T.J. Watt", ["TJ Watt"], "2021"),
    ("Troy Polamalu", ["Polamalu"], "2010"),
    ("Khalil Mack", ["Mack"], "2016"),
    ("Ed Reed", ["Reed"], "2004"),
    ("Brian Urlacher", ["Urlacher"], "2005"),
    ("Charles Woodson", ["Woodson"], "2009"),
    ("Michael Strahan", ["Strahan"], "2001"),
    ("Nick Bosa", ["Bosa"], "2022"),
    ("Luke Kuechly", ["Kuechly"], "2013"),
    ("Terrell Suggs", ["Suggs"], "2011"),
    ("Jason Taylor", [], "2006"),
    ("Derrick Brooks", ["Brooks"], "2002"),
    ("Patrick Surtain II", ["Pat Surtain", "Surtain"], "2024"),
    ("James Harrison", ["Harrison"], "2008"),
    ("Stephon Gilmore", ["Gilmore"], "2019"),
    ("Bob Sanders", ["Sanders"], "2007"),
])

P("nfl-opoy-2000", "NFL awards", "Name a player who has won AP Offensive Player of the Year since the 2000 season", "2000+", "opoy",
  ["opoy", "opoy2", "nfl_honors"], [
    ("Patrick Mahomes", ["Mahomes"], "2018"),
    ("Tom Brady", ["Brady"], "2007, 2010"),
    ("Peyton Manning", ["Peyton"], "2004, 2013"),
    ("Saquon Barkley", ["Barkley"], "2024"),
    ("Derrick Henry", ["Henry"], "2020"),
    ("Christian McCaffrey", ["CMC", "McCaffrey"], "2023"),
    ("Drew Brees", ["Brees"], "2008, 2011"),
    ("Cam Newton", ["Newton"], "2015"),
    ("Adrian Peterson", ["Peterson"], "2012"),
    ("LaDainian Tomlinson", ["LT", "Tomlinson"], "2006"),
    ("Cooper Kupp", ["Kupp"], "2021"),
    ("Justin Jefferson", ["Jefferson"], "2022"),
    ("Marshall Faulk", ["Faulk"], "2000, 2001"),
    ("Matt Ryan", ["Ryan"], "2016"),
    ("Todd Gurley", ["Gurley"], "2017"),
    ("Shaun Alexander", ["Alexander"], "2005"),
    ("Chris Johnson", ["CJ2K"], "2009"),
    ("DeMarco Murray", ["Murray"], "2014"),
    ("Jaxon Smith-Njigba", ["JSN", "Smith Njigba", "Jaxon Smith Njigba"], "2025"),
    ("Michael Thomas", [], "2019"),
    ("Jamal Lewis", [], "2003"),
    ("Priest Holmes", ["Holmes"], "2002"),
])

P("nfl-oroy-2000", "NFL awards", "Name a player who has won AP Offensive Rookie of the Year since the 2000 season", "2000+", "oroy",
  ["oroy", "oroy2", "nfl_honors"], [
    ("Justin Herbert", ["Herbert"], "2020"),
    ("Ja'Marr Chase", ["Chase", "Jamarr Chase"], "2021"),
    ("Saquon Barkley", ["Barkley"], "2018"),
    ("Cam Newton", ["Newton"], "2011"),
    ("Ben Roethlisberger", ["Big Ben", "Roethlisberger"], "2004"),
    ("Adrian Peterson", ["Peterson"], "2007"),
    ("Odell Beckham Jr.", ["OBJ", "Odell Beckham", "Beckham"], "2014"),
    ("Dak Prescott", ["Prescott"], "2016"),
    ("Kyler Murray", [], "2019"),
    ("Jayden Daniels", ["Daniels"], "2024"),
    ("C.J. Stroud", ["CJ Stroud", "Stroud"], "2023"),
    ("Todd Gurley", ["Gurley"], "2015"),
    ("Alvin Kamara", ["Kamara"], "2017"),
    ("Robert Griffin III", ["RG3", "Robert Griffin", "Griffin"], "2012"),
    ("Matt Ryan", ["Ryan"], "2008"),
    ("Sam Bradford", ["Bradford"], "2010"),
    ("Garrett Wilson", [], "2022"),
    ("Vince Young", [], "2006"),
    ("Eddie Lacy", ["Lacy"], "2013"),
    ("Percy Harvin", ["Harvin"], "2009"),
    ("Clinton Portis", ["Portis"], "2002"),
    ("Tetairoa McMillan", ["McMillan", "Tet McMillan"], "2025"),
    ("Cadillac Williams", ["Carnell Williams", "Carnell Cadillac Williams"], "2005"),
    ("Anquan Boldin", ["Boldin"], "2003"),
    ("Anthony Thomas", [], "2001"),
    ("Mike Anderson", [], "2000"),
])

P("nfl-droy-2000", "NFL awards", "Name a player who has won AP Defensive Rookie of the Year since the 2000 season", "2000+", "droy",
  ["droy", "droy2", "nfl_honors"], [
    ("Micah Parsons", ["Parsons"], "2021"),
    ("Nick Bosa", ["Bosa"], "2019"),
    ("Von Miller", ["Miller"], "2011"),
    ("Aaron Donald", ["Donald"], "2014"),
    ("Luke Kuechly", ["Kuechly"], "2012"),
    ("Ndamukong Suh", ["Suh"], "2010"),
    ("Brian Urlacher", ["Urlacher"], "2000"),
    ("Julius Peppers", ["Peppers"], "2002"),
    ("Patrick Willis", ["Willis"], "2007"),
    ("Chase Young", [], "2020"),
    ("Joey Bosa", [], "2016"),
    ("Sauce Gardner", ["Ahmad Gardner", "Gardner"], "2022"),
    ("Will Anderson Jr.", ["Will Anderson", "Anderson"], "2023"),
    ("Terrell Suggs", ["Suggs"], "2003"),
    ("Marshon Lattimore", ["Lattimore"], "2017"),
    ("Jared Verse", ["Verse"], "2024"),
    ("Marcus Peters", ["Peters"], "2015"),
    ("Shawne Merriman", ["Merriman"], "2005"),
    ("Brian Cushing", ["Cushing"], "2009"),
    ("DeMeco Ryans", ["Ryans"], "2006"),
    ("Sheldon Richardson", ["Richardson"], "2013"),
    ("Jerod Mayo", ["Mayo"], "2008"),
    ("Jonathan Vilma", ["Vilma"], "2004"),
    ("Shaquille Leonard", ["Darius Leonard", "Shaq Leonard", "Leonard"], "2018"),
    ("Carson Schwesinger", ["Schwesinger"], "2025"),
    ("Kendrell Bell", [], "2001"),
])

# ============================================================================================= draft & stadiums
P("first-overall-pick-2000", "NFL Draft", "Name a player drafted No. 1 overall in the NFL Draft since 2000", "2000+", "no1",
  ["draft1", "draft2"], [
    ("Joe Burrow", ["Burrow"], "2020, Bengals"),
    ("Trevor Lawrence", ["Lawrence"], "2021, Jaguars"),
    ("Caleb Williams", [], "2024, Bears"),
    ("Cam Newton", ["Newton"], "2011, Panthers"),
    ("Andrew Luck", ["Luck"], "2012, Colts"),
    ("Myles Garrett", ["Garrett"], "2017, Browns"),
    ("Kyler Murray", [], "2019, Cardinals"),
    ("Baker Mayfield", ["Mayfield"], "2018, Browns"),
    ("Jameis Winston", ["Winston"], "2015, Buccaneers"),
    ("Eli Manning", ["Eli"], "2004, Chargers (traded to the Giants)"),
    ("Matthew Stafford", ["Matt Stafford"], "2009, Lions"),
    ("Bryce Young", ["Young"], "2023, Panthers"),
    ("Cam Ward", ["Ward"], "2025, Titans"),
    ("Michael Vick", ["Mike Vick", "Vick"], "2001, Falcons"),
    ("Carson Palmer", ["Palmer"], "2003, Bengals"),
    ("Jared Goff", ["Goff"], "2016, Rams"),
    ("Jadeveon Clowney", ["Clowney"], "2014, Texans"),
    ("Fernando Mendoza", ["Mendoza"], "2026, Raiders"),
    ("Sam Bradford", ["Bradford"], "2010, Rams"),
    ("JaMarcus Russell", ["Russell"], "2007, Raiders"),
    ("Alex Smith", [], "2005, 49ers"),
    ("Mario Williams", [], "2006, Texans"),
    ("Travon Walker", ["Walker"], "2022, Jaguars"),
    ("David Carr", ["Carr"], "2002, Texans"),
    ("Jake Long", ["Long"], "2008, Dolphins"),
    ("Eric Fisher", ["Fisher"], "2013, Chiefs"),
    ("Courtney Brown", ["Brown"], "2000, Browns"),
])

P("team-no1-pick-2000", "NFL Draft", "Name a team that has made the No. 1 overall pick in the NFL Draft since 2000", "2000+", "no1",
  ["draft1", "draft2"], team_rows(
    ["CLE", "HOU", "CIN", "LV", "LAR", "CAR", "JAX", "IND", "KC", "TB", "ARI", "CHI", "TEN", "DET", "LAC", "SF", "ATL", "MIA"],
    {"CLE": "2000, 2017, 2018", "HOU": "2002, 2006, 2014", "CIN": "2003, 2020", "LV": "2007 (Oakland), 2026", "LAR": "2010 (St. Louis), 2016",
     "CAR": "2011, 2023", "JAX": "2021, 2022", "IND": "2012", "KC": "2013", "TB": "2015", "ARI": "2019", "CHI": "2024", "TEN": "2025",
     "DET": "2009", "LAC": "2004 (San Diego)", "SF": "2005", "ATL": "2001", "MIA": "2008"}))

P("current-stadium", "Stadiums & teams", "Name a current NFL stadium", "all", "stadiums",
  ["stadiums", "stadiums2", "stadium_chron"], [
    ("AT&T Stadium", ["ATT Stadium", "Cowboys Stadium"], "Cowboys, Arlington TX"),
    ("Lambeau Field", ["Lambeau"], "Packers, Green Bay WI"),
    ("SoFi Stadium", ["Sofi"], "Rams and Chargers, Inglewood CA"),
    ("Arrowhead Stadium", ["Arrowhead", "GEHA Field at Arrowhead Stadium", "GEHA Field"], "Chiefs, Kansas City MO"),
    ("Soldier Field", [], "Bears, Chicago IL"),
    ("MetLife Stadium", ["Met Life Stadium"], "Giants and Jets, East Rutherford NJ"),
    ("Allegiant Stadium", [], "Raiders, Paradise NV"),
    ("Caesars Superdome", ["Superdome", "Mercedes-Benz Superdome", "Mercedes Benz Superdome", "Louisiana Superdome"], "Saints, New Orleans LA"),
    ("Lincoln Financial Field", ["The Linc", "Linc"], "Eagles, Philadelphia PA"),
    ("Gillette Stadium", [], "Patriots, Foxborough MA"),
    ("Mercedes-Benz Stadium", ["Mercedes Benz Stadium"], "Falcons, Atlanta GA"),
    ("Hard Rock Stadium", ["Sun Life Stadium", "Dolphin Stadium", "Pro Player Stadium", "Joe Robbie Stadium"], "Dolphins, Miami Gardens FL"),
    ("Lumen Field", ["CenturyLink Field", "Qwest Field"], "Seahawks, Seattle WA"),
    ("Levi's Stadium", ["Levis Stadium"], "49ers, Santa Clara CA"),
    ("Highmark Stadium", ["Ralph Wilson Stadium", "New Era Field", "Bills Stadium", "Rich Stadium"], "Bills, Orchard Park NY (new stadium opened 2026)"),
    ("Acrisure Stadium", ["Heinz Field"], "Steelers, Pittsburgh PA"),
    ("Empower Field at Mile High", ["Mile High", "Mile High Stadium", "Invesco Field", "Sports Authority Field"], "Broncos, Denver CO"),
    ("Raymond James Stadium", ["Ray Jay"], "Buccaneers, Tampa FL"),
    ("U.S. Bank Stadium", ["US Bank Stadium"], "Vikings, Minneapolis MN"),
    ("Lucas Oil Stadium", [], "Colts, Indianapolis IN"),
    ("State Farm Stadium", ["University of Phoenix Stadium", "Univ of Phoenix Stadium"], "Cardinals, Glendale AZ"),
    ("Ford Field", [], "Lions, Detroit MI"),
    ("Bank of America Stadium", ["BofA Stadium"], "Panthers, Charlotte NC"),
    ("M&T Bank Stadium", ["MT Bank Stadium", "Ravens Stadium"], "Ravens, Baltimore MD"),
    ("Huntington Bank Field", ["FirstEnergy Stadium", "Cleveland Browns Stadium"], "Browns, Cleveland OH"),
    ("Nissan Stadium", ["LP Field", "Adelphia Coliseum"], "Titans, Nashville TN"),
    ("NRG Stadium", ["Reliant Stadium"], "Texans, Houston TX"),
    ("EverBank Stadium", ["TIAA Bank Field", "EverBank Field", "Alltel Stadium", "Jacksonville Municipal Stadium"], "Jaguars, Jacksonville FL"),
    ("Northwest Stadium", ["FedExField", "FedEx Field", "Jack Kent Cooke Stadium"], "Commanders, Landover MD"),
    ("Paycor Stadium", ["Paul Brown Stadium"], "Bengals, Cincinnati OH"),
])

P("team-new-stadium-2000", "Stadiums & teams", "Name a team whose current home stadium opened in 2000 or later", "2000+", "stadiums",
  ["stadiums", "stadiums2", "stadium_chron"], team_rows(
    ["DAL", "LV", "LAR", "LAC", "SF", "ATL", "MIN", "NYG", "NYJ", "PHI", "NE", "SEA", "PIT", "DEN", "DET", "ARI", "IND", "HOU", "CIN", "BUF"],
    {"DAL": "AT&T Stadium, 2009", "LV": "Allegiant Stadium, 2020", "LAR": "SoFi Stadium, 2020", "LAC": "SoFi Stadium, 2020",
     "SF": "Levi's Stadium, 2014", "ATL": "Mercedes-Benz Stadium, 2017", "MIN": "U.S. Bank Stadium, 2016", "NYG": "MetLife Stadium, 2010",
     "NYJ": "MetLife Stadium, 2010", "PHI": "Lincoln Financial Field, 2003", "NE": "Gillette Stadium, 2002", "SEA": "Lumen Field, 2002",
     "PIT": "Acrisure Stadium, 2001", "DEN": "Empower Field at Mile High, 2001", "DET": "Ford Field, 2002", "ARI": "State Farm Stadium, 2006",
     "IND": "Lucas Oil Stadium, 2008", "HOU": "NRG Stadium, 2002", "CIN": "Paycor Stadium, 2000", "BUF": "Highmark Stadium, 2026"}))

P("nfl-mascot", "Stadiums & teams", "Name an NFL team mascot", "all", "mascots",
  ["mascots", "mascots2"], [
    ("Swoop", [], "Eagles"),
    ("Rowdy", [], "Cowboys"),
    ("Blitz", [], "Seahawks"),
    ("K.C. Wolf", ["KC Wolf", "Wolf"], "Chiefs"),
    ("Freddie Falcon", [], "Falcons"),
    ("Sir Purr", [], "Panthers"),
    ("Pat Patriot", [], "Patriots"),
    ("Steely McBeam", [], "Steelers"),
    ("Billy Buffalo", [], "Bills"),
    ("Captain Fear", [], "Buccaneers"),
    ("Viktor the Viking", ["Viktor", "Victor"], "Vikings"),
    ("Sourdough Sam", [], "49ers"),
    ("Big Red", [], "Cardinals"),
    ("Rampage", [], "Rams"),
    ("Jaxson de Ville", ["Jaxson", "Jaxon de Ville"], "Jaguars"),
    ("Roary", [], "Lions"),
    ("Staley Da Bear", ["Staley", "Staley the Bear"], "Bears"),
    ("Who Dey", [], "Bengals"),
    ("Toro", [], "Texans"),
    ("Miles", [], "Broncos"),
    ("Poe", [], "Ravens"),
    ("Blue", [], "Colts"),
    ("T-Rac", ["Trac", "T Rac"], "Titans"),
    ("T.D.", ["TD"], "Dolphins"),
    ("Gumbo", [], "Saints"),
    ("Chomps", [], "Browns"),
    ("Raider Rusher", [], "Raiders"),
    ("Major Tuddy", [], "Commanders (introduced 2023)"),
    ("Sir Saint", [], "Saints"),
    ("Thunder", [], "Broncos (live horse)"),
    ("Boom", [], "Seahawks"),
    ("Taima", [], "Seahawks (live hawk)"),
    ("Brownie the Elf", ["Brownie"], "Browns"),
])

P("sb-winning-teams", "Super Bowl", "Name a team that has won a Super Bowl", "all", "sb-team",
  ["sb_champs", "franchise_hof"], team_rows(
    ["NE", "PIT", "SF", "DAL", "GB", "KC", "NYG", "DEN", "LV", "WAS", "MIA", "PHI", "SEA", "BAL", "LAR", "IND", "CHI", "NO", "TB", "NYJ"],
    {"*": "Super Bowl champion (through LX, 2026)"}))

# ============================================================================================= career records
P("career-sacks-100", "Career records", "Name a player with 100 or more official career sacks", "all", "records-def",
  ["sacks", "sacks2"], [
    ("Reggie White", ["White"], "198 sacks"),
    ("Bruce Smith", [], "200 sacks, the NFL record"),
    ("Lawrence Taylor", ["LT"], "132.5 official sacks"),
    ("J.J. Watt", ["JJ Watt"], "114.5 sacks"),
    ("Von Miller", ["Miller"], "130+ sacks"),
    ("Michael Strahan", ["Strahan"], "141.5 sacks"),
    ("Julius Peppers", ["Peppers"], "159.5 sacks"),
    ("Aaron Donald", ["Donald"], "111 sacks"),
    ("DeMarcus Ware", ["Ware"], "138.5 sacks"),
    ("Khalil Mack", ["Mack"], "113 sacks"),
    ("T.J. Watt", ["TJ Watt"], "100+ sacks"),
    ("Myles Garrett", ["Garrett"], "125+ sacks"),
    ("Jason Taylor", [], "139.5 sacks"),
    ("Terrell Suggs", ["Suggs"], "139 sacks"),
    ("Kevin Greene", ["Greene"], "160 sacks"),
    ("Chris Doleman", ["Doleman"], "150.5 sacks"),
    ("Richard Dent", ["Dent"], "137.5 sacks"),
    ("Derrick Thomas", [], "126.5 sacks"),
    ("Dwight Freeney", ["Freeney"], "125.5 sacks"),
    ("Jared Allen", ["Allen"], "136 sacks"),
    ("Cameron Jordan", ["Jordan"], "130+ sacks"),
    ("John Randle", ["Randle"], "137.5 sacks"),
    ("Rickey Jackson", ["Jackson"], "128 sacks"),
    ("Charles Haley", ["Haley"], "100.5 sacks"),
    ("Simeon Rice", ["Rice"], "122 sacks"),
    ("Calais Campbell", ["Campbell"], "117+ sacks"),
    ("Robert Mathis", ["Mathis"], "123 sacks"),
    ("John Abraham", ["Abraham"], "133.5 sacks"),
    ("Leslie O'Neal", ["O'Neal"], "132.5 sacks"),
    ("Clyde Simmons", ["Simmons"], "121.5 sacks"),
    ("Chandler Jones", [], "112 sacks"),
    ("Justin Houston", ["Houston"], "112 sacks"),
    ("Danielle Hunter", ["Hunter"], "114.5+ sacks"),
    ("Cameron Wake", ["Wake"], "100.5 sacks"),
    ("Elvis Dumervil", ["Dumervil"], "105.5 sacks"),
    ("Robert Quinn", ["Quinn"], "102+ sacks"),
    ("Carlos Dunlap", ["Dunlap"], "100 sacks"),
    ("Andre Tippett", ["Tippett"], "100 sacks"),
    ("Neil Smith", [], "104.5 sacks"),
    ("Pat Swilling", ["Swilling"], "107.5 sacks"),
    ("Sean Jones", [], "113 sacks"),
    ("Kevin Carter", [], "104.5 sacks"),
    ("Greg Townsend", ["Townsend"], "109.5 sacks"),
    ("Trace Armstrong", ["Armstrong"], "106 sacks"),
    ("Jim Jeffcoat", ["Jeffcoat"], "102.5 sacks"),
    ("William Fuller", ["Fuller"], "100.5 sacks"),
])

P("career-rushing-10k", "Career records", "Name a player with 10,000 or more career rushing yards", "all", "records-off",
  ["rush", "rush2"], [
    ("Emmitt Smith", ["Smith"], "18,355, the NFL record"),
    ("Walter Payton", ["Payton", "Sweetness"], "16,726"),
    ("Barry Sanders", ["Sanders"], "15,269"),
    ("Adrian Peterson", ["AP", "Peterson"], "14,918"),
    ("Derrick Henry", ["Henry"], "13,000+"),
    ("LaDainian Tomlinson", ["LT", "Tomlinson"], "13,684"),
    ("Frank Gore", ["Gore"], "16,000"),
    ("Eric Dickerson", ["Dickerson"], "13,259"),
    ("Jim Brown", ["Brown"], "12,312"),
    ("Curtis Martin", ["Martin"], "14,101"),
    ("Jerome Bettis", ["Bettis"], "13,662"),
    ("Marshall Faulk", ["Faulk"], "12,279"),
    ("Marcus Allen", ["Allen"], "12,243"),
    ("Tony Dorsett", ["Dorsett"], "12,739"),
    ("O.J. Simpson", ["OJ Simpson", "Simpson"], "11,236"),
    ("Thurman Thomas", [], "12,074"),
    ("Franco Harris", ["Harris"], "12,120"),
    ("Edgerrin James", ["James"], "12,246"),
    ("Marshawn Lynch", ["Lynch"], "10,413"),
    ("LeSean McCoy", ["Shady McCoy", "McCoy"], "11,000+"),
    ("Fred Taylor", [], "11,695"),
    ("Steven Jackson", [], "11,438"),
    ("John Riggins", ["Riggins"], "11,352"),
    ("Corey Dillon", ["Dillon"], "11,241"),
    ("Warrick Dunn", ["Dunn"], "10,967"),
    ("Jamal Lewis", [], "10,607"),
    ("Tiki Barber", ["Barber"], "10,449"),
    ("Eddie George", ["George"], "10,441"),
    ("Ricky Williams", [], "10,009"),
    ("Ricky Watters", ["Watters"], "10,643"),
    ("Thomas Jones", [], "10,591"),
    ("Ottis Anderson", [], "10,273"),
])

P("career-receiving-13k", "Career records", "Name a player with 13,000 or more career receiving yards", "all", "records-off",
  ["rec", "rec2"], [
    ("Jerry Rice", ["Rice"], "22,895, the NFL record"),
    ("Larry Fitzgerald", ["Fitzgerald", "Fitz"], "17,492"),
    ("Terrell Owens", ["T.O.", "TO", "Owens"], "15,934"),
    ("Randy Moss", ["Moss"], "15,292"),
    ("Tony Gonzalez", ["Gonzalez"], "15,127, a tight end"),
    ("Marvin Harrison", ["Harrison"], "14,580"),
    ("Tim Brown", [], "14,934"),
    ("Isaac Bruce", ["Bruce"], "15,208"),
    ("Steve Smith Sr.", ["Steve Smith", "Smith"], "14,731"),
    ("Andre Johnson", ["Johnson"], "14,185"),
    ("Julio Jones", ["Jones"], "13,703"),
    ("Reggie Wayne", ["Wayne"], "14,345"),
    ("Cris Carter", ["Carter"], "13,899"),
    ("Anquan Boldin", ["Boldin"], "13,779"),
    ("Jason Witten", ["Witten"], "13,046, a tight end"),
    ("DeAndre Hopkins", ["Hopkins", "Nuk Hopkins"], "13,295"),
    ("Steve Largent", ["Largent"], "13,089"),
    ("Torry Holt", ["Holt"], "13,382"),
    ("James Lofton", ["Lofton"], "14,004"),
    ("Andre Reed", ["Reed"], "13,198"),
    ("Henry Ellard", ["Ellard"], "13,777"),
])

P("career-passing-47k", "Career records", "Name a quarterback with 47,000 or more career passing yards", "all", "records-off",
  ["pass", "pass2"], [
    ("Tom Brady", ["Brady"], "89,214, the NFL record"),
    ("Drew Brees", ["Brees"], "80,358"),
    ("Peyton Manning", ["Peyton"], "71,940"),
    ("Brett Favre", ["Favre"], "71,838"),
    ("Aaron Rodgers", ["Rodgers"], "66,000+"),
    ("Matthew Stafford", ["Matt Stafford"], "64,000+"),
    ("Ben Roethlisberger", ["Big Ben", "Roethlisberger"], "64,088"),
    ("Philip Rivers", ["Rivers"], "63,984"),
    ("Matt Ryan", ["Ryan"], "62,000+"),
    ("Dan Marino", ["Marino"], "61,361"),
    ("Eli Manning", ["Eli"], "57,023"),
    ("John Elway", ["Elway"], "51,475"),
    ("Warren Moon", ["Moon"], "49,325 (NFL regular season)"),
    ("Joe Flacco", ["Flacco"], "48,176"),
    ("Fran Tarkenton", ["Tarkenton"], "47,003"),
])

P("career-fg-400", "Career records", "Name a kicker with 400 or more career field goals made", "all", "records-kick",
  ["fg", "fg2"], [
    ("Adam Vinatieri", ["Vinatieri"], "599, the NFL record"),
    ("Justin Tucker", ["Tucker"], "417"),
    ("Sebastian Janikowski", ["Janikowski", "Sea Bass"], "436"),
    ("Morten Andersen", ["Andersen"], "565"),
    ("Gary Anderson", ["Anderson"], "538"),
    ("Phil Dawson", ["Dawson"], "441"),
    ("Mason Crosby", ["Crosby"], "400"),
    ("Jason Elam", ["Elam"], "436"),
    ("Robbie Gould", ["Gould"], "447"),
    ("Nick Folk", ["Folk"], "400+"),
    ("Matt Prater", ["Prater"], "410+"),
    ("Jason Hanson", ["Hanson"], "495"),
    ("Matt Stover", ["Stover"], "471"),
    ("John Kasay", ["Kasay"], "461"),
    ("John Carney", ["Carney"], "478"),
])

# ============================================================================================= pre-2000 (kept to a minimum)
P("hof-quarterback", "Hall of Fame", "Name a Pro Football Hall of Fame quarterback", "pre2000", "hof-qb",
  ["hof_pos", "hof_wiki", "hof_2026"], [
    ("Joe Montana", ["Montana"], "Class of 2000"),
    ("Dan Marino", ["Marino"], "Class of 2005"),
    ("John Elway", ["Elway"], "Class of 2004"),
    ("Peyton Manning", ["Peyton"], "Class of 2021"),
    ("Brett Favre", ["Favre"], "Class of 2016"),
    ("Troy Aikman", ["Aikman"], "Class of 2006"),
    ("Steve Young", [], "Class of 2005"),
    ("Terry Bradshaw", ["Bradshaw"], "Class of 1989"),
    ("Joe Namath", ["Namath", "Broadway Joe"], "Class of 1985"),
    ("Johnny Unitas", ["Unitas", "Johnny U"], "Class of 1979"),
    ("Bart Starr", ["Starr"], "Class of 1977"),
    ("Roger Staubach", ["Staubach"], "Class of 1985"),
    ("Jim Kelly", [], "Class of 2002"),
    ("Kurt Warner", ["Warner"], "Class of 2017"),
    ("Dan Fouts", ["Fouts"], "Class of 1993"),
    ("Warren Moon", ["Moon"], "Class of 2006"),
    ("Fran Tarkenton", ["Tarkenton"], "Class of 1986"),
    ("Drew Brees", ["Brees"], "Class of 2026"),
    ("Len Dawson", ["Dawson"], "Class of 1987"),
    ("Bob Griese", ["Griese"], "Class of 1990"),
    ("Ken Stabler", ["Stabler", "Snake Stabler"], "Class of 2016"),
    ("Otto Graham", ["Graham"], "Class of 1965"),
    ("Sammy Baugh", ["Baugh", "Slingin Sammy Baugh"], "Class of 1963"),
    ("Sonny Jurgensen", ["Jurgensen"], "Class of 1983"),
    ("Y.A. Tittle", ["YA Tittle", "Tittle"], "Class of 1971"),
    ("Bobby Layne", ["Layne"], "Class of 1967"),
    ("Norm Van Brocklin", ["Van Brocklin"], "Class of 1971"),
    ("George Blanda", ["Blanda"], "Class of 1981"),
    ("Sid Luckman", ["Luckman"], "Class of 1965"),
    ("Bob Waterfield", ["Waterfield"], "Class of 1965"),
    ("Arnie Herber", ["Herber"], "Class of 1966"),
    ("Benny Friedman", ["Friedman"], "Class of 2005"),
    ("Jimmy Conzelman", ["Conzelman"], "Class of 1964"),
    ("Paddy Driscoll", ["John Driscoll", "Driscoll"], "Class of 1965"),
])

P("sb-winning-qb-pre2000", "Super Bowl", "Name a quarterback who won a Super Bowl before the 2000 season", "pre2000", "sb-qb-old",
  ["sb_qbs", "sb_qbs_hof", "sb_champs"], [
    ("Joe Montana", ["Montana"], "XVI, XIX, XXIII, XXIV (49ers)"),
    ("Troy Aikman", ["Aikman"], "XXVII, XXVIII, XXX (Cowboys)"),
    ("John Elway", ["Elway"], "XXXII, XXXIII (Broncos)"),
    ("Terry Bradshaw", ["Bradshaw"], "IX, X, XIII, XIV (Steelers)"),
    ("Joe Namath", ["Namath"], "III (Jets)"),
    ("Bart Starr", ["Starr"], "I, II (Packers)"),
    ("Steve Young", [], "XXIX (49ers)"),
    ("Roger Staubach", ["Staubach"], "VI, XII (Cowboys)"),
    ("Brett Favre", ["Favre"], "XXXI (Packers)"),
    ("Johnny Unitas", ["Unitas"], "V (Colts)"),
    ("Bob Griese", ["Griese"], "VII, VIII (Dolphins)"),
    ("Phil Simms", ["Simms"], "XXI (Giants)"),
    ("Ken Stabler", ["Stabler"], "XI (Raiders)"),
    ("Len Dawson", ["Dawson"], "IV (Chiefs)"),
    ("Kurt Warner", ["Warner"], "XXXIV (Rams, January 2000)"),
    ("Jim McMahon", ["McMahon"], "XX (Bears)"),
    ("Jim Plunkett", ["Plunkett"], "XV, XVIII (Raiders)"),
    ("Doug Williams", [], "XXII (Redskins)"),
    ("Mark Rypien", ["Rypien"], "XXVI (Redskins)"),
    ("Joe Theismann", ["Theismann"], "XVII (Redskins)"),
    ("Jeff Hostetler", ["Hostetler"], "XXV (Giants)"),
])

P("sb-mvp-pre2000", "Super Bowl", "Name a Super Bowl MVP from before the 2000 season", "pre2000", "sb-mvp-old",
  ["sb_mvp", "sb_mvp2"], [
    ("Joe Montana", ["Montana"], "XVI, XIX, XXIV"),
    ("Bart Starr", ["Starr"], "I, II"),
    ("Terry Bradshaw", ["Bradshaw"], "XIII, XIV"),
    ("Joe Namath", ["Namath"], "III"),
    ("Troy Aikman", ["Aikman"], "XXVII"),
    ("Steve Young", [], "XXIX"),
    ("John Elway", ["Elway"], "XXXIII"),
    ("Emmitt Smith", [], "XXVIII"),
    ("Jerry Rice", ["Rice"], "XXIII"),
    ("Terrell Davis", [], "XXXII"),
    ("Roger Staubach", ["Staubach"], "VI"),
    ("Marcus Allen", ["Allen"], "XVIII"),
    ("Lynn Swann", ["Swann"], "X"),
    ("Franco Harris", ["Harris"], "IX"),
    ("Larry Csonka", ["Csonka"], "VIII"),
    ("Richard Dent", ["Dent"], "XX"),
    ("Phil Simms", ["Simms"], "XXI"),
    ("Doug Williams", [], "XXII"),
    ("Ottis Anderson", [], "XXV"),
    ("Mark Rypien", ["Rypien"], "XXVI"),
    ("Len Dawson", ["Dawson"], "IV"),
    ("Kurt Warner", ["Warner"], "XXXIV (January 2000)"),
    ("Jim Plunkett", ["Plunkett"], "XV"),
    ("John Riggins", ["Riggins"], "XVII"),
    ("Fred Biletnikoff", ["Biletnikoff"], "XI"),
    ("Harvey Martin", [], "XII (co-MVP)"),
    ("Randy White", [], "XII (co-MVP)"),
    ("Larry Brown", [], "XXX (Cowboys CB)"),
    ("Desmond Howard", [], "XXXI (Packers returner)"),
    ("Chuck Howley", ["Howley"], "V (Cowboys LB, MVP despite the loss)"),
    ("Jake Scott", [], "VII (Dolphins S)"),
])

P("sb-coach-pre2000", "Super Bowl", "Name a head coach who won a Super Bowl before the 2000 season", "pre2000", "sb-coach-old",
  ["sb_coaches", "sb_coaches2"], [
    ("Vince Lombardi", ["Lombardi"], "I, II (Packers)"),
    ("Don Shula", ["Shula"], "VII, VIII (Dolphins)"),
    ("Bill Walsh", ["Walsh"], "XVI, XIX, XXIII (49ers)"),
    ("Chuck Noll", ["Noll"], "IX, X, XIII, XIV (Steelers)"),
    ("Tom Landry", ["Landry"], "VI, XII (Cowboys)"),
    ("Joe Gibbs", ["Gibbs"], "XVII, XXII, XXVI (Redskins)"),
    ("Bill Parcells", ["Parcells"], "XXI, XXV (Giants)"),
    ("Jimmy Johnson", [], "XXVII, XXVIII (Cowboys)"),
    ("Mike Ditka", ["Ditka"], "XX (Bears)"),
    ("John Madden", ["Madden"], "XI (Raiders)"),
    ("George Seifert", ["Seifert"], "XXIV, XXIX (49ers)"),
    ("Mike Shanahan", ["Shanahan"], "XXXII, XXXIII (Broncos)"),
    ("Dick Vermeil", ["Vermeil"], "XXXIV (Rams, January 2000)"),
    ("Mike Holmgren", ["Holmgren"], "XXXI (Packers)"),
    ("Barry Switzer", ["Switzer"], "XXX (Cowboys)"),
    ("Tom Flores", ["Flores"], "XV, XVIII (Raiders)"),
    ("Hank Stram", ["Stram"], "IV (Chiefs)"),
    ("Weeb Ewbank", ["Ewbank"], "III (Jets)"),
    ("Don McCafferty", ["McCafferty"], "V (Colts)"),
])


def main():
    os.makedirs(OUT, exist_ok=True)
    for f in os.listdir(OUT):
        if f.endswith(".json"):
            os.remove(os.path.join(OUT, f))
    for p in PROMPTS:
        doc = {"version": VERSION, "key": p["key"], "cat": p["cat"], "text": p["text"], "era": p["era"], "group": p["group"],
               "sources": p["sources"], "answers": build_answers(p["rows"], p["src"], p["sources"])}
        with open(os.path.join(OUT, p["key"] + ".json"), "w") as fh:
            json.dump(doc, fh, indent=1, ensure_ascii=False)
            fh.write("\n")
    print(len(PROMPTS), "prompts;", sum(1 for p in PROMPTS if p["era"] == "pre2000"), "pre-2000")


if __name__ == "__main__":
    main()
