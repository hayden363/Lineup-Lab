"""
GAME-DAY WEATHER — forecast at kickoff for outdoor games
========================================================
The nflverse schedule only fills in wind and temperature after a game is
played. For upcoming games this pulls the hourly forecast for the stadium at
kickoff from Open-Meteo (free, no key; forecasts reach about 16 days out).

Indoor games (roof "dome"/"closed") get no forecast. Retractable roofs that
the schedule doesn't mark get one, labelled as possibly closed.

Degradation index (0 = no effect, 100 = severe), from the factors that move
passing and kicking:
    wind     15 mph -> 25, 20 mph -> 50, 25+ mph -> 75
    rain     >= 1 mm/h -> +15, >= 3 mm/h -> +30
    snow     any -> +35
    cold     <= 20 F -> +15
"""

import datetime as dt
import time
from concurrent.futures import ThreadPoolExecutor

from . import sleeper

FORECAST_URL = ("https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
                "&hourly=temperature_2m,wind_speed_10m,wind_gusts_10m,precipitation,snowfall"
                "&wind_speed_unit=mph&temperature_unit=fahrenheit&timezone=America%2FNew_York"
                "&start_date={day}&end_date={day}")
WEATHER_TTL = 60 * 60
FAIL_TTL = 10 * 60          # a lookup that failed is not retried for ten minutes: one slow weather service must not slow a page
TIMEOUT = 4                 # seconds a forecast request may take
_FAILED = {}                # cache name -> when it last failed
FORECAST_DAYS = 15

# (lat, lon) by nflverse stadium_id.
STADIUMS = {
    "ATL97": (33.755, -84.401), "BAL00": (39.278, -76.623), "BOS00": (42.091, -71.264),
    "BUF00": (42.774, -78.787), "CAR00": (35.226, -80.853), "CHI98": (41.862, -87.617),
    "CIN00": (39.095, -84.516), "CLE00": (41.506, -81.700), "DAL00": (32.748, -97.093),
    "DEN00": (39.744, -105.020), "DET00": (42.340, -83.046), "GNB00": (44.501, -88.062),
    "HOU00": (29.685, -95.411), "IND00": (39.760, -86.164), "JAX00": (30.324, -81.637),
    "KAN00": (39.049, -94.484), "LAX01": (33.953, -118.339), "LON00": (51.556, -0.280),
    "LON02": (51.604, -0.066), "MAD01": (40.453, -3.688), "MEL00": (-37.820, 144.983),
    "MEX00": (19.303, -99.150), "MIA00": (25.958, -80.239), "MIN01": (44.974, -93.258),
    "MUN01": (48.219, 11.625), "NAS00": (36.166, -86.771), "NOR00": (29.951, -90.081),
    "NYC01": (40.814, -74.074), "PAR00": (48.924, 2.360), "PHI00": (39.901, -75.168),
    "PHO00": (33.528, -112.263), "PIT00": (40.447, -80.016), "RIO00": (-22.912, -43.230),
    "SEA00": (47.595, -122.332), "SFO01": (37.403, -121.970), "TAM00": (27.976, -82.503),
    "VEG00": (36.091, -115.184), "WAS00": (38.908, -76.864),
}
RETRACTABLE = {"ATL97", "DAL00", "HOU00", "IND00", "PHO00"}
INDOOR_ROOFS = {"dome", "closed"}


def degradation(wind, precip, snow, temp):
    """(index 0-100, label, reasons) from kickoff conditions."""
    idx, why = 0, []
    if wind is not None:
        if wind >= 25:
            idx += 75
        elif wind >= 20:
            idx += 50
        elif wind >= 15:
            idx += 25
        if wind >= 15:
            why.append(f"wind {wind:.0f} mph")
    if precip is not None and precip >= 1:
        idx += 30 if precip >= 3 else 15
        why.append("heavy rain" if precip >= 3 else "rain")
    if snow is not None and snow > 0:
        idx += 35
        why.append("snow")
    if temp is not None and temp <= 20:
        idx += 15
        why.append(f"{temp:.0f}°F")
    idx = min(100, idx)
    label = "none" if idx == 0 else "mild" if idx < 30 else "significant" if idx < 60 else "severe"
    return idx, label, why


def kickoff_forecast(stadium_id, roof, gameday, gametime, today=None):
    """Forecast dict for one game, or None (indoors, unknown stadium, too far
    out, already played, or the service is unreachable)."""
    if roof in INDOOR_ROOFS or stadium_id not in STADIUMS or not gameday:
        return None
    today = today or dt.date.today()
    day = dt.date.fromisoformat(str(gameday)[:10])
    if day < today or (day - today).days > FORECAST_DAYS:
        return None
    hour = int(str(gametime or "13:00").split(":")[0])
    lat, lon = STADIUMS[stadium_id]
    name = f"wx_{stadium_id}_{day.isoformat()}"
    if time.time() - _FAILED.get(name, 0) < FAIL_TTL:
        return None
    try:
        data = sleeper._cached_get(FORECAST_URL.format(lat=lat, lon=lon, day=day.isoformat()), name, WEATHER_TTL, timeout=TIMEOUT)
        h = data["hourly"]
        # Average kickoff through the next two hours: roughly the first half.
        idx = [i for i, t in enumerate(h["time"]) if hour <= int(t[11:13]) <= hour + 2]
        if not idx:
            return None
        avg = lambda k: sum(h[k][i] or 0 for i in idx) / len(idx)
        wind, gust, temp = avg("wind_speed_10m"), avg("wind_gusts_10m"), avg("temperature_2m")
        precip, snow = avg("precipitation"), avg("snowfall")
    except Exception as e:
        _FAILED[name] = time.time()
        print(f"[weather] forecast unavailable for {stadium_id} {day}: {e}")
        return None
    index, label, why = degradation(wind, precip, snow, temp)
    return {"temp": round(temp), "wind": round(wind), "gust": round(gust), "precip_mm": round(precip, 1),
            "snow_cm": round(snow, 1), "index": index, "label": label, "reasons": why,
            "maybe_closed": stadium_id in RETRACTABLE and roof not in ("open", "outdoors")}


def prefetch(schedule, week):
    """Warm the forecast cache for every outdoor game in `week`, all at once, so the per-player lookups that follow
    are instant. Returns how many games it asked about; never raises."""
    try:
        s = schedule[schedule["game_type"] == "REG"] if "game_type" in schedule.columns else schedule
        g = s[(s["week"] == week) & (~s["roof"].isin(INDOOR_ROOFS))] if "roof" in s.columns else s[s["week"] == week]
        games = [(r.get("stadium_id"), r.get("roof"), r.get("gameday"), r.get("gametime")) for r in g.to_dict("records")]
    except Exception:
        return 0

    def one(a):
        try:
            kickoff_forecast(*a)
        except Exception as e:
            print(f"[weather] prefetch skipped one game: {e}")
    if games:
        with ThreadPoolExecutor(max_workers=8) as ex:
            list(ex.map(one, games))
    return len(games)
