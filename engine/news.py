"""
NEWS — real public NFL RSS, filtered to players you actually care about
==========================================================================
Pulls from public, free NFL news RSS feeds (exactly what RSS syndication
is for — no scraping, no paywall, no ToS issue) and filters headlines
down to whoever's on your roster or your Sleeper opponent's roster this
week. Cached to disk for a short TTL so the app isn't hammering these
feeds on every page load.

Optional: a short AI-written summary of one player's real matched
headlines (see ai_summary_for_player below), via the Claude API. Same
"works fine without it, just doesn't appear" pattern as Gmail
(engine/mail.py) and Google sign-in (engine/oauth.py) — set
ANTHROPIC_API_KEY in `.env` to turn it on; nothing breaks if you don't.
"""

import os
import re
import time

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
}

TTL_SECONDS = 20 * 60
_MEM_CACHE = {}
_AI_SUMMARY_CACHE = {}   # (player_id, tuple of matched article links) -> summary text
AI_SUMMARY_TTL_SECONDS = 60 * 60

_OG_IMAGE_RE = re.compile(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', re.IGNORECASE)


def _enclosure_image(entry):
    """Some feeds (CBS Sports) attach the article's real photo directly as
    an RSS enclosure link — free, no extra request."""
    for link in entry.get("links", []) or []:
        if link.get("rel") == "enclosure" and str(link.get("type", "")).startswith("image"):
            return link.get("href")
    return None


def _scrape_og_image(article_url):
    """Feeds that don't attach an image (ESPN) — a best-effort, short-timeout
    fetch of the article's own <meta property="og:image"> tag, i.e. the
    real photo the publisher itself put on the page. Never raises — a
    failure here just means that one headline renders without a photo."""
    try:
        resp = requests.get(article_url, timeout=4, headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code != 200:
            return None
        m = _OG_IMAGE_RE.search(resp.text)
        return m.group(1) if m else None
    except Exception:
        return None


def _fetch_feed(name, url, force=False):
    now = time.time()
    if not force and name in _MEM_CACHE and (now - _MEM_CACHE[name][0]) < TTL_SECONDS:
        return _MEM_CACHE[name][1]

    parsed = feedparser.parse(url)
    items = []
    for e in parsed.entries[:40]:
        link = e.get("link", "")
        image = _enclosure_image(e) or (_scrape_og_image(link) if link else None)
        items.append({
            "source": name,
            "title": e.get("title", ""),
            "link": link,
            "summary": re.sub("<[^<]+?>", "", e.get("summary", ""))[:280],
            "published": e.get("published", ""),
            "image": image,
        })
    _MEM_CACHE[name] = (now, items)
    return items


def all_headlines(force=False):
    items = []
    for name, url in FEEDS.items():
        try:
            items.extend(_fetch_feed(name, url, force=force))
        except Exception as e:
            print(f"[news] couldn't fetch {name}: {e}")
    return items


def _name_variants(full_name):
    """Full-name match only. A last-name-alone fallback sounds appealing
    (headlines often drop first names on repeat mentions) but in practice
    it false-positives constantly — a story about "Xavier Woods" reads as
    being about your "Robert Woods" the moment last-name matching is loose
    enough to allow it, and most surnames are shared by several NFL
    players. Full-name-only trades some recall for a filter you can
    actually trust."""
    return {full_name.lower()}


def filter_for_players(items, players):
    """players: [{player_id, player_display_name}, ...]. Returns items with
    a `matched_players` list attached (only items that matched at least
    one), newest-first order preserved from the feed."""
    lookup = []
    for p in players:
        name = p.get("player_display_name")
        if not name:
            continue
        lookup.append((p["player_id"], name, _name_variants(name)))

    out = []
    for item in items:
        haystack = f"{item['title']} {item['summary']}".lower()
        matched = [{"player_id": pid, "name": name} for pid, name, variants in lookup
                   if any(v in haystack for v in variants)]
        if matched:
            out.append({**item, "matched_players": matched})
    return out


def player_news(player_display_name, player_id=None, force=False):
    """Real news items about ONE player, newest first — the per-player
    feed for a player detail view, not the roster-wide filter above.
    Reuses the same real headlines/filtering, just a one-player lookup
    list instead of a whole roster."""
    items = all_headlines(force=force)
    lookup_id = player_id or player_display_name
    return filter_for_players(items, [{"player_id": lookup_id, "player_display_name": player_display_name}])


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
