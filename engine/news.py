"""
NEWS — real public NFL RSS, filtered to players you actually care about
==========================================================================
Pulls from public, free NFL news RSS feeds (exactly what RSS syndication
is for — no scraping, no paywall, no ToS issue) and filters headlines
down to whoever's on your roster or your Sleeper opponent's roster this
week. Cached to disk for a short TTL so the app isn't hammering these
feeds on every page load.
"""

import os
import re
import time

import feedparser
import requests

from .data import CACHE_DIR

FEEDS = {
    "ESPN": "https://www.espn.com/espn/rss/nfl/news",
    "CBS Sports": "https://www.cbssports.com/rss/headlines/nfl/",
}

TTL_SECONDS = 20 * 60
_MEM_CACHE = {}

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
