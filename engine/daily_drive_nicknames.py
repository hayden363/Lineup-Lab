"""
DAILY DRIVE NICKNAMES — famous names fans type that the player's real name can't produce
=======================================================================================
Keyed by gsis player id (the answer `id`), so a nickname only ever counts for its own player: "CMC" never matches a
different Chris, and the two Mike Williamses can't be confused. dd.check_answer treats a nickname as an exact answer
(it counts even for top-tier answers that otherwise need the exact name).

Initials (ARSB, JSN, OBJ) don't need to be listed here: check_answer builds those from the name automatically when
they are 3+ letters and unique within the question. List initials here only when the auto rule can't build them
(2-letter ones like "AB", or names stored without the suffix fans include).
"""

NICKNAMES = {
    "00-0033280": ["CMC"],                                        # Christian McCaffrey
    "00-0025389": ["Megatron"],                                   # Calvin Johnson
    "00-0027656": ["Gronk"],                                      # Rob Gronkowski
    "00-0025399": ["Beast Mode"],                                 # Marshawn Lynch
    "00-0019596": ["TB12"],                                       # Tom Brady
    "00-0035662": ["Hollywood", "Hollywood Brown"],               # Marquise Brown
    "00-0037190": ["Sauce", "Ahmad Gardner"],                     # Sauce Gardner
    "00-0014324": ["Prime Time", "Neon Deion"],                   # Deion Sanders
    "00-0020397": ["Ochocinco", "Ocho Cinco", "Chad Ochocinco"],  # Chad Johnson
    "00-0012478": ["T.O."],                                       # Terrell Owens
    "00-0020536": ["LT"],                                         # LaDainian Tomlinson
    "00-0025394": ["AP", "All Day"],                              # Adrian Peterson (Vikings)
    "00-0033040": ["Cheetah"],                                    # Tyreek Hill
    "00-0032764": ["King Henry"],                                 # Derrick Henry
    "00-0033045": ["Zeke"],                                       # Ezekiel Elliott
    "00-0022924": ["Big Ben"],                                    # Ben Roethlisberger
    "00-0027793": ["AB"],                                         # Antonio Brown
    "00-0030564": ["Nuk", "D-Hop", "DHop"],                       # DeAndre Hopkins
    "00-0036963": ["ARSB", "Sun God", "Amon Ra"],                 # Amon-Ra St. Brown
    "00-0038543": ["JSN"],                                        # Jaxon Smith-Njigba
    "00-0031235": ["OBJ", "Odell"],                               # Odell Beckham Jr.
    "00-0039849": ["MHJ", "MHJr", "Marvin Harrison Jr"],          # Marvin Harrison Jr.
    "00-0039893": ["BTJ", "Brian Thomas Jr"],                     # Brian Thomas Jr.
    "00-0038134": ["K9", "Kenneth Walker III"],                   # Kenneth Walker III
    "00-0039075": ["Puka"],                                       # Puka Nacua
    "00-0034844": ["Saquon"],                                     # Saquon Barkley
    "00-0038542": ["Bijan"],                                      # Bijan Robinson
    "00-0033873": ["Pat Mahomes"],                                # Patrick Mahomes
    "00-0036900": ["JaMarr"],                                     # Ja'Marr Chase
}
