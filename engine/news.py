"""
NEWS — real public NFL RSS, filtered to players you actually care about
==========================================================================
Pulls from public, free NFL news RSS feeds (exactly what RSS syndication
is for — no scraping, no paywall, no ToS issue) and filters headlines
down to whoever's on your roster or your Sleeper opponent's roster this
week.

Speed. A request never waits on more than one round of parallel, time-boxed feed
downloads, and usually waits on none:
  * the feeds download in parallel, each with a hard connect/read timeout, so one slow
    publisher can't stall the tab;
  * the cache is stale-while-revalidate: past its TTL we keep serving the last good copy
    instantly and refresh in a background thread (warm() fills it at startup);
  * article photos are never fetched inside a request. Feeds that attach one (CBS) show
    it at once; for the rest a small background pool reads each article's og:image and
    the photo appears on the next load.
The old version downloaded the feeds one after another and then, for every ESPN item,
fetched the article page itself (up to 40 serial requests, 4 s timeout each) before it
could answer.

Relevance. Names are matched after folding punctuation, apostrophes (curly too) and
suffixes, so "Kenneth Walker III" matches "Kenneth Walker" and "Ja'Marr Chase" matches
"Ja’Marr Chase" / "JaMarr Chase". A surname alone is accepted only when that player's own
team is also named in the same text (so "Walker" + "Seahawks" is Kenneth Walker, a bare
"Walker" is nobody), and never when two of the players being matched share it on one team.
Team and opponent scopes can add lower-ranked "team news" for teams you start players from.

Optional: a short AI-written summary of one player's real matched
headlines (see ai_summary_for_player below), via the Claude API. Same
"works fine without it, just doesn't appear" pattern as Gmail
(engine/mail.py) and Google sign-in (engine/oauth.py) — set
ANTHROPIC_API_KEY in `.env` to turn it on; nothing breaks if you don't.
"""

import calendar
import os
import re
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, wait

import feedparser
import requests

from .data import CACHE_DIR

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed — env vars can still be set another way

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
AI_SUMMARY_MODEL = "claude-opus-5"

FEEDS = {
    "ESPN": "https://www.espn.com/espn/rss/nfl/news",
    "CBS Sports": "https://www.cbssports.com/rss/headlines/nfl/",
    # Both added after team/opponent-scoped News came back empty in
    # practice: ESPN/CBS's own top-NFL-news feeds are real but shallow
    # (~40 entries each, general breaking news) — good odds of matching a
    # top-of-the-league star, poor odds of matching most of an actual
    # 15-player roster. These two are real, public RSS (checked
    # robots.txt on both — no disallow on the feed itself, no bot-specific
    # block) and skew toward exactly the per-team, per-player granularity
    # (injury/practice reports, week-N starter decisions) this app's
    # name-matching filter needs. Confirmed live: ProFootballRumors is
    # already carrying real "Week 2" team-by-team QB/injury calls.
    # Deliberately skipped: Yahoo Sports (real, working feed, but their
    # robots.txt explicitly disallows the `anthropic-ai` user-agent
    # site-wide — honoring that regardless of what a generic client
    # would technically get away with); RotoWire (real feed, but its
    # public RSS only returns 5 items, suggesting the full feed sits
    # behind a paid tier — not confirmed enough to rely on).
    "Pro Football Rumors": "https://www.profootballrumors.com/feed",
    "ProFootballTalk": "https://profootballtalk.nbcsports.com/feed/",
}

TTL_SECONDS = 20 * 60
FEED_TIMEOUT = (3, 6)          # (connect, read) seconds for one feed download
BLOCK_TIMEOUT = 8.0            # the most a request waits on a COLD cache, all feeds in parallel
IMAGE_TIMEOUT = 3
IMAGE_SCRAPE_LIMIT = 24        # newest items per feed that get a background photo lookup
IMAGE_TTL_SECONDS = 6 * 60 * 60
IMAGE_RETRY_SECONDS = 15 * 60  # a lookup that found nothing (or failed) is retried after this
USER_AGENT = "Mozilla/5.0 (compatible; LineupLab/1.0)"

_FEED_CACHE = {}               # feed name -> {"at": epoch, "items": [...]}
_IMAGE_CACHE = {}              # article url -> (epoch, image url or None)
_INFLIGHT = {}                 # feed name -> the Future refreshing it right now
_LOCK = threading.Lock()
_FEED_POOL = ThreadPoolExecutor(max_workers=8, thread_name_prefix="news-feed")
_IMAGE_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="news-img")
_AI_SUMMARY_CACHE = {}   # (player_id, tuple of matched article links) -> summary text
AI_SUMMARY_TTL_SECONDS = 60 * 60

_OG_IMAGE_RE = re.compile(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', re.IGNORECASE)


# ----------------------------------------------------------------- fetching ----
def _enclosure_image(entry):
    """Some feeds (CBS Sports) attach the article's real photo directly as
    an RSS enclosure link — free, no extra request."""
    for link in entry.get("links", []) or []:
        if link.get("rel") == "enclosure" and str(link.get("type", "")).startswith("image"):
            return link.get("href")
    return None


def _scrape_og_image(article_url):
    """The article's own <meta property="og:image"> — the real photo the publisher
    put on the page. Best effort with a short timeout; never raises."""
    try:
        resp = requests.get(article_url, timeout=IMAGE_TIMEOUT, headers={"User-Agent": USER_AGENT})
        if resp.status_code != 200:
            return None
        m = _OG_IMAGE_RE.search(resp.text)
        return m.group(1) if m else None
    except Exception:
        return None


def _fill_image(item):
    """Background job: look up one item's photo and attach it. Failures are remembered
    too, so a dead page isn't retried on every refresh."""
    link = item.get("link")
    img = _scrape_og_image(link)
    _IMAGE_CACHE[link] = (time.time(), img)
    if img:
        item["image"] = img


def _schedule_images(items):
    now = time.time()
    for it in items[:IMAGE_SCRAPE_LIMIT]:
        link = it.get("link")
        if it.get("image") or not link:
            continue
        known = _IMAGE_CACHE.get(link)
        if known and now - known[0] < (IMAGE_TTL_SECONDS if known[1] else IMAGE_RETRY_SECONDS):
            it["image"] = known[1]
            continue
        _IMAGE_CACHE[link] = (now, None)       # claim it so two refreshes don't both scrape
        _IMAGE_POOL.submit(_fill_image, it)


def _published_ts(entry):
    st = entry.get("published_parsed") or entry.get("updated_parsed")
    try:
        return calendar.timegm(st) if st else 0
    except (TypeError, ValueError, OverflowError):
        return 0


def _download_feed(name, url):
    resp = requests.get(url, timeout=FEED_TIMEOUT, headers={"User-Agent": USER_AGENT})
    resp.raise_for_status()
    parsed = feedparser.parse(resp.content)
    items = []
    for e in parsed.entries[:40]:
        link = e.get("link", "")
        items.append({
            "source": name,
            "title": e.get("title", ""),
            "link": link,
            "summary": re.sub("<[^<]+?>", "", e.get("summary", ""))[:280],
            "published": e.get("published", ""),
            "ts": _published_ts(e),
            "image": _enclosure_image(e),
        })
    return items


def _refresh_feed(name, url):
    """Download one feed into the cache. Returns True if it landed. A failure keeps the
    previous copy, so a flaky publisher never blanks the tab."""
    try:
        items = _download_feed(name, url)
        _schedule_images(items)
        with _LOCK:
            _FEED_CACHE[name] = {"at": time.time(), "items": items}
        return True
    except Exception as e:
        print(f"[news] couldn't fetch {name}: {e}")
        return False
    finally:
        with _LOCK:
            _INFLIGHT.pop(name, None)


def _start_refresh(name, url):
    """The Future refreshing this feed: the one already running if there is one (so
    simultaneous cold requests share a single download and all wait for it), else a new one."""
    with _LOCK:
        running = _INFLIGHT.get(name)
        if running is not None:
            return running
        fut = _FEED_POOL.submit(_refresh_feed, name, url)
        _INFLIGHT[name] = fut          # the worker's cleanup needs _LOCK, so it can't run before this line
        return fut


def warm():
    """Fill the cache in the background (called at startup) so the first visitor isn't the one waiting."""
    for name, url in FEEDS.items():
        _start_refresh(name, url)


def all_headlines(force=False):
    """Every cached headline, feeds in FEEDS order. Warm cache: instant, and a stale feed
    is refreshed in the background. Cold (or force=True): all feeds download in parallel
    and we wait at most BLOCK_TIMEOUT for them; whatever arrived is returned."""
    now = time.time()
    pending = []
    for name, url in FEEDS.items():
        cached = _FEED_CACHE.get(name)
        if cached is None or force:
            pending.append(_start_refresh(name, url))
        elif now - cached["at"] >= TTL_SECONDS:
            _start_refresh(name, url)            # serve the stale copy now, refresh behind it
    if pending:
        wait(pending, timeout=BLOCK_TIMEOUT)
    items = []
    for name in FEEDS:
        cached = _FEED_CACHE.get(name)
        if cached:
            items.extend(cached["items"])
    return items


def clear_cache():
    """Forget every cached feed and photo and drop queued photo lookups (used by tests)."""
    global _IMAGE_POOL
    with _LOCK:
        _FEED_CACHE.clear()
        _IMAGE_CACHE.clear()
        _INFLIGHT.clear()
        old, _IMAGE_POOL = _IMAGE_POOL, ThreadPoolExecutor(max_workers=4, thread_name_prefix="news-img")
    old.shutdown(wait=False, cancel_futures=True)


# ----------------------------------------------------------------- matching ----
_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}

# nflverse team code -> (nickname words, city words). Cities that are also a person's name or
# shared by two teams are left out ("washington", "new york", "los angeles").
_TEAMS = {
    "ARI": (("cardinals",), ("arizona",)), "ATL": (("falcons",), ("atlanta",)),
    "BAL": (("ravens",), ("baltimore",)), "BUF": (("bills",), ("buffalo",)),
    "CAR": (("panthers",), ("carolina",)), "CHI": (("bears",), ("chicago",)),
    "CIN": (("bengals",), ("cincinnati",)), "CLE": (("browns",), ("cleveland",)),
    "DAL": (("cowboys",), ("dallas",)), "DEN": (("broncos",), ("denver",)),
    "DET": (("lions",), ("detroit",)), "GB": (("packers",), ("green bay",)),
    "HOU": (("texans",), ("houston",)), "IND": (("colts",), ("indianapolis",)),
    "JAX": (("jaguars", "jags"), ("jacksonville",)), "KC": (("chiefs",), ("kansas city",)),
    "LV": (("raiders",), ("las vegas",)), "LAC": (("chargers",), ()), "LA": (("rams",), ()),
    "MIA": (("dolphins",), ("miami",)), "MIN": (("vikings",), ("minnesota",)),
    "NE": (("patriots", "pats"), ("new england",)), "NO": (("saints",), ("new orleans",)),
    "NYG": (("giants",), ()), "NYJ": (("jets",), ()), "PHI": (("eagles",), ("philadelphia",)),
    "PIT": (("steelers",), ("pittsburgh",)), "SF": (("49ers", "niners"), ("san francisco",)),
    "SEA": (("seahawks",), ("seattle",)), "TB": (("buccaneers", "bucs"), ("tampa bay",)),
    "TEN": (("titans",), ("tennessee",)), "WAS": (("commanders",), ()),
}
_TEAM_ALIAS = {"WSH": "WAS", "LAR": "LA", "JAC": "JAX", "OAK": "LV", "SD": "LAC", "STL": "LA", "ARZ": "ARI"}
TEAM_NEWS_CAP = 10


def _team_key(team):
    t = str(team or "").upper()
    t = _TEAM_ALIAS.get(t, t)
    return t if t in _TEAMS else None


def _norm(text):
    """Lower-case, possessives and apostrophes (straight or curly) dropped, periods dropped,
    everything else non-alphanumeric a space, padded with spaces so a plain `in` is
    word-bounded: " josh allen " in _norm("Josh Allen's ankle")."""
    t = (text or "").lower()
    t = re.sub(r"(?<=[a-z])['’‘]s(?![a-z])", "", t)
    t = re.sub(r"['’‘`]", "", t)
    t = t.replace(".", "")
    return " " + re.sub(r"[^a-z0-9]+", " ", t).strip() + " "


def _name_tokens(full_name):
    toks = _norm(full_name).split()
    while len(toks) > 1 and toks[-1] in _SUFFIXES:
        toks.pop()
    return toks


def _team_phrases(team):
    nick, cities = _TEAMS[team]
    return [f" {w} " for w in nick + cities]


def _prepare(players):
    """One lookup record per player; surnames shared by two of them on a team are disabled."""
    prepared = []
    for p in players:
        name = p.get("player_display_name")
        if not name:
            continue
        toks = _name_tokens(name)
        if not toks:
            continue
        last = toks[-1] if len(toks) > 1 and len(toks[-1]) >= 4 else None
        team = _team_key(p.get("recent_team") or p.get("team"))
        prepared.append({"player_id": p["player_id"], "name": name, "full": " " + " ".join(toks) + " ",
                         "last": f" {last} " if last else None, "team": team})
    counts = Counter((r["last"], r["team"]) for r in prepared if r["last"] and r["team"])
    for r in prepared:
        if r["last"] and (not r["team"] or counts[(r["last"], r["team"])] > 1):
            r["last"] = None
    return prepared


def filter_for_players(items, players, include_team_news=False):
    """players: [{player_id, player_display_name, recent_team?}, ...]. Returns copies of the
    items that match, each with `matched_players` ([{player_id, name}]), `match_kind`
    ("name" | "surname" | "team") and `relevance`, strongest first and newest first within a
    strength (feed order when there is no timestamp).

      name     the full name (suffix/punctuation folded) appears in the title or summary
      surname  the surname AND that player's team appear in the same text
      team     (only with include_team_news) a team one of your players is on is mentioned and
               no player matched; at most TEAM_NEWS_CAP of these, with `matched_teams`
    """
    prepared = _prepare(players)
    team_phrases = {}
    for r in prepared:
        if r["team"] and r["team"] not in team_phrases:
            team_phrases[r["team"]] = _team_phrases(r["team"])

    out, team_items = [], []
    for item in items:
        title_n = _norm(item.get("title", ""))
        hay = _norm(f"{item.get('title', '')} {item.get('summary', '')}")
        matched, kind, in_title = [], None, False
        teams_in_text = {t for t, phrases in team_phrases.items() if any(ph in hay for ph in phrases)}
        for r in prepared:
            if r["full"] in hay:
                strength = "name"
            elif r["last"] and r["last"] in hay and r["team"] in teams_in_text:
                strength = "surname"
            else:
                continue
            matched.append({"player_id": r["player_id"], "name": r["name"]})
            if strength == "name":
                kind = "name"
                in_title = in_title or r["full"] in title_n
            elif kind is None:
                kind = "surname"
        if matched:
            rel = (3.0 if kind == "name" else 2.0) + (0.5 if in_title else 0.0)
            out.append({**item, "matched_players": matched, "match_kind": kind, "relevance": rel})
        elif include_team_news and teams_in_text:
            team_items.append({**item, "matched_players": [], "match_kind": "team", "relevance": 1.0,
                               "matched_teams": sorted(teams_in_text)})
    out.sort(key=lambda it: (-it["relevance"], -(it.get("ts") or 0)))
    team_items.sort(key=lambda it: -(it.get("ts") or 0))
    return out + team_items[:TEAM_NEWS_CAP]


def player_news(player_display_name, player_id=None, force=False, team=None):
    """Real news items about ONE player, strongest match first — the per-player feed for
    a player detail view. Pass his team to also catch "Walker" + "Seahawks" mentions."""
    items = all_headlines(force=force)
    lookup_id = player_id or player_display_name
    return filter_for_players(items, [{"player_id": lookup_id, "player_display_name": player_display_name,
                                       "recent_team": team}])


def ai_summary_for_player(player_display_name, matched_items, position=None, injury_status=None, player_id=None):
    """A short, factual AI-written summary of this player's real matched
    news items — grounded only in the headlines/snippets already matched
    by player_news/filter_for_players, nothing invented. Returns None
    (never raises) when there's nothing to summarize, ANTHROPIC_API_KEY
    isn't set, or the API call fails for any reason — a missing summary
    just means the raw headlines show instead, same "degrades, doesn't
    break" contract as Gmail/Google sign-in elsewhere in this app."""
    if not matched_items:
        return None
    if not ANTHROPIC_API_KEY:
        return None

    cache_key = (player_id or player_display_name, tuple(it["link"] for it in matched_items[:6]))
    now = time.time()
    cached = _AI_SUMMARY_CACHE.get(cache_key)
    if cached is not None and (now - cached[0]) < AI_SUMMARY_TTL_SECONDS:
        return cached[1]

    try:
        import anthropic
    except ImportError:
        print("[news] ANTHROPIC_API_KEY is set but the `anthropic` package isn't installed "
              "(pip install anthropic) — skipping AI summary")
        return None

    sources_text = "\n\n".join(
        f"[{it['source']}] {it['title']}\n{it['summary']}" for it in matched_items[:6]
    )
    context = player_display_name
    if position:
        context += f" ({position})"
    if injury_status:
        context += f" — current injury designation on file: {injury_status}"

    prompt = (
        f"Player: {context}\n\n"
        f"Real, recent headlines/snippets about this player from real NFL news sources:\n\n"
        f"{sources_text}\n\n"
        "Write a short, plain, factual summary (3-5 sentences) of what these sources "
        "actually say about this player right now — fantasy-football-relevant context "
        "(injury/health status, role, recent performance or news) if it's in there. "
        "Ground this ONLY in the text above; don't add anything the sources don't say, "
        "and don't give betting or gambling advice."
    )

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model=AI_SUMMARY_MODEL,
            max_tokens=300,
            output_config={"effort": "low"},   # short factual summary — not a task that needs deep reasoning
            messages=[{"role": "user", "content": prompt}],
        )
        text = next((b.text for b in response.content if b.type == "text"), None)
        summary = text.strip() if text else None
    except Exception as e:
        print(f"[news] AI summary failed (showing raw headlines only): {e}")
        summary = None

    _AI_SUMMARY_CACHE[cache_key] = (now, summary)
    return summary
