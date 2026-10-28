"""
LINEUP LAB PICK — our own prediction for one game
=================================================
Each team's expected score is the average of how many points it scores and how many the other side allows
(both pulled toward the league average when the sample is small), plus a small home-field edge. When a betting
line exists, the pick is the average of that and the betting market's implied scores: the market is the best
single number there is, and our team rates add what it may be slow on. The win chance is a normal curve on the
predicted margin (NFL margins have a spread of about 13 points).

It is a transparent estimate, not a guarantee, and says whether the market was part of it.
"""
import math

LEAGUE_PPG = 22.5
HOME_EDGE = 2.0            # points, split between the two sides
SHRINK_GAMES = 4           # a team's rate counts n / (n + 4) of its own games, the rest is league average
MARGIN_SD = 13.0
MARKET_WEIGHT = 0.5


def _shrunk(rate, n):
    k = n / (n + SHRINK_GAMES)
    return LEAGUE_PPG + (rate - LEAGUE_PPG) * k


def _phi(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def predict(home, away, market):
    """`home`/`away`: {games, pf_pg, pa_pg} (points scored and allowed per game this season). `market`: optional
    {home_implied, away_implied}. None when either team has no games yet."""
    if not home or not away or not home.get("games") or not away.get("games"):
        return None
    h_pf, h_pa = _shrunk(home["pf_pg"], home["games"]), _shrunk(home["pa_pg"], home["games"])
    a_pf, a_pa = _shrunk(away["pf_pg"], away["games"]), _shrunk(away["pa_pg"], away["games"])
    h_model = (h_pf + a_pa) / 2 + HOME_EDGE / 2
    a_model = (a_pf + h_pa) / 2 - HOME_EDGE / 2
    h, a = h_model, a_model
    used = bool(market and market.get("home_implied") is not None and market.get("away_implied") is not None)
    if used:
        h = (1 - MARKET_WEIGHT) * h_model + MARKET_WEIGHT * market["home_implied"]
        a = (1 - MARKET_WEIGHT) * a_model + MARKET_WEIGHT * market["away_implied"]
    margin = h - a
    home_pct = round(100 * _phi(margin / MARGIN_SD))
    home_pct = min(97, max(3, home_pct))
    out = {"home_score": round(h, 1), "away_score": round(a, 1), "total": round(round(h, 1) + round(a, 1), 1),
           "margin": round(round(h, 1) - round(a, 1), 1), "home_win_pct": home_pct, "away_win_pct": 100 - home_pct,
           "pick": "home" if margin >= 0 else "away", "used_market": used,
           "model_margin": round(h_model - a_model, 1)}
    if used:
        mk_margin = market["home_implied"] - market["away_implied"]
        out["vs_market"] = {"market_margin": round(mk_margin, 1), "margin_edge": round((h_model - a_model) - mk_margin, 1)}
    return out
