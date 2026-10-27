"""engine/news fetching: parallel, time-boxed, stale-while-revalidate, photos off the request path.
A local fake publisher stands in for ESPN/CBS/PFR/PFT, so there's no network."""
import threading
import time
import unittest
import unittest.mock
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from engine import news


class Publisher:
    """/feed?delay=&n=&tag=&enc=  /article?delay=  /hang  /bad  — and a per-path hit counter."""

    def __init__(self):
        self.hits = {}
        self.mode = {}                     # path -> "bad" to start failing
        pub = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                u = urlparse(self.path)
                q = {k: v[0] for k, v in parse_qs(u.query).items()}
                key = u.path + ("?" + q["tag"] if "tag" in q else "")
                pub.hits[key] = pub.hits.get(key, 0) + 1
                time.sleep(float(q.get("delay", 0)))
                if u.path == "/hang":
                    time.sleep(30)
                if u.path == "/bad" or pub.mode.get(q.get("tag")) == "bad":
                    self.send_response(500); self.end_headers(); return
                if u.path == "/feed":
                    tag, n = q.get("tag", "x"), int(q.get("n", 10))
                    port = self.server.server_address[1]
                    items = "".join(
                        f"<item><title>{tag} headline {i} CeeDee Lamb</title><link>http://127.0.0.1:{port}/article?delay={q.get('adelay', 0)}&amp;i={tag}{i}</link>"
                        f"<description>summary {i}</description><pubDate>Mon, 26 Oct 2026 12:{i % 60:02d}:00 GMT</pubDate></item>"
                        for i in range(n))
                    body = f"<?xml version='1.0'?><rss version='2.0'><channel><title>t</title>{items}</channel></rss>".encode()
                    self.send_response(200); self.send_header("Content-Type", "application/rss+xml"); self.end_headers(); self.wfile.write(body); return
                if u.path == "/article":
                    body = b"<html><head><meta property='og:image' content='http://img.example/p.jpg'></head></html>"
                    self.send_response(200); self.send_header("Content-Type", "text/html"); self.end_headers(); self.wfile.write(body); return
                self.send_response(404); self.end_headers()

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def url(self, path, **q):
        qs = "&".join(f"{k}={v}" for k, v in q.items())
        return f"http://127.0.0.1:{self.port}{path}?{qs}"

    def close(self):
        self.server.shutdown()


RSS = """<?xml version="1.0"?><rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/"
 xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel><title>t</title>{items}</channel></rss>"""


def entries(xml_items):
    import feedparser
    return feedparser.parse(RSS.format(items=xml_items)).entries


class FeedImageExtractionTests(unittest.TestCase):
    """The photo comes out of the feed itself, with no request to the article."""

    def img(self, xml_item):
        return news._enclosure_image(entries(f"<item><title>x</title>{xml_item}</item>")[0])

    def test_enclosure(self):
        self.assertEqual(self.img('<enclosure url="https://cdn.x/a.jpg" type="image/jpeg" length="1"/>'), "https://cdn.x/a.jpg")

    def test_media_thumbnail_and_media_content(self):
        self.assertEqual(self.img('<media:thumbnail url="https://cdn.x/t.jpg"/>'), "https://cdn.x/t.jpg")
        self.assertEqual(self.img('<media:content url="https://cdn.x/c.jpg" medium="image"/>'), "https://cdn.x/c.jpg")

    def test_a_video_media_content_is_not_a_photo(self):
        self.assertIsNone(self.img('<media:content url="https://cdn.x/v.mp4" medium="video" type="video/mp4"/>'))

    def test_first_real_img_in_the_body_skipping_pixels_and_tiny_images(self):
        body = ('<description><![CDATA[<img src="https://stats.x/pixel.gif" width="1" height="1">'
                '<img src="https://cdn.x/tiny.png" width="20" height="20">'
                '<img src="https://cdn.x/hero.jpg" width="600"> text]]></description>')
        self.assertEqual(self.img(body), "https://cdn.x/hero.jpg")
        self.assertEqual(self.img('<content:encoded><![CDATA[<p><img src="//cdn.x/p.jpg"></p>]]></content:encoded>'), "https://cdn.x/p.jpg")

    def test_plain_http_photos_are_upgraded_because_the_csp_blocks_them(self):
        # server.py sends `img-src 'self' https: data:`; an http:// image would never render
        self.assertEqual(self.img('<enclosure url="http://cdn.x/a.jpg" type="image/jpeg" length="1"/>'), "https://cdn.x/a.jpg")
        self.assertEqual(self.img('<media:thumbnail url="http://cdn.x/t.jpg"/>'), "https://cdn.x/t.jpg")
        self.assertEqual(self.img('<description><![CDATA[<img src="http://cdn.x/b.jpg" width="400">]]></description>'), "https://cdn.x/b.jpg")

    def test_data_uris_and_relative_paths_are_ignored_and_none_when_nothing(self):
        self.assertIsNone(self.img('<description><![CDATA[<img src="data:image/png;base64,AAAA"><img src="/rel.jpg">]]></description>'))
        self.assertIsNone(self.img("<description>just words</description>"))

    def test_download_keeps_the_photo_and_strips_the_tags_from_the_summary(self):
        pub = Publisher()
        self.addCleanup(pub.close)
        item = news._download_feed("t", pub.url("/feed", tag="t", n=1))[0]            # feed has no photo -> None
        self.assertIsNone(item["image"])
        xml = RSS.format(items='<item><title>T</title><link>http://l</link><description><![CDATA[<img src="https://cdn.x/h.jpg" width="500"> Hello]]></description></item>')
        with unittest.mock.patch.object(news.requests, "get") as g:
            g.return_value.content = xml.encode(); g.return_value.raise_for_status = lambda: None
            got = news._download_feed("t", "http://feed")[0]
        self.assertEqual((got["image"], got["summary"].strip()), ("https://cdn.x/h.jpg", "Hello"))


class HeadOnlyScrapeTests(unittest.TestCase):
    def setUp(self):
        self.pub = Publisher()
        self.addCleanup(self.pub.close)

    def test_finds_og_image_in_either_attribute_order_and_stops_reading_early(self):
        import http.server
        big = b"<html><head><meta content='https://cdn.x/rev.jpg' property='og:image'></head><body>" + b"x" * 5_000_000
        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def do_GET(self):
                self.send_response(200); self.send_header("Content-Length", str(len(big))); self.end_headers()
                try: self.wfile.write(big)
                except Exception: pass
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        t = time.time()
        self.assertEqual(news._scrape_og_image(f"http://127.0.0.1:{srv.server_address[1]}/a"), "https://cdn.x/rev.jpg")
        self.assertLess(time.time() - t, 1.0)

    def test_page_without_the_tag_gives_up_at_the_end_of_head(self):
        self.assertIsNone(news._scrape_og_image(self.pub.url("/missing")))        # 404
        self.assertIsNone(news._scrape_og_image("http://127.0.0.1:1/x"))          # refused, never raises


class FetchTests(unittest.TestCase):
    def setUp(self):
        self.pub = Publisher()
        self.addCleanup(self.pub.close)
        saved = (news.FEEDS, news.FEED_TIMEOUT, news.BLOCK_TIMEOUT, news.TTL_SECONDS, news.IMAGE_TIMEOUT)
        self.addCleanup(lambda: (setattr(news, "FEEDS", saved[0]), setattr(news, "FEED_TIMEOUT", saved[1]),
                                 setattr(news, "BLOCK_TIMEOUT", saved[2]), setattr(news, "TTL_SECONDS", saved[3]),
                                 setattr(news, "IMAGE_TIMEOUT", saved[4]), news.clear_cache()))
        news.FEED_TIMEOUT, news.BLOCK_TIMEOUT, news.IMAGE_TIMEOUT = (1, 1.0), 2.5, 1
        news.clear_cache()

    def feeds(self, **kw):
        news.FEEDS = {name: self.pub.url("/feed", tag=name, **q) for name, q in kw.items()}

    def test_cold_cache_downloads_feeds_in_parallel_and_never_scrapes_photos_inline(self):
        # 4 feeds x 0.4 s latency, 40 items each with 0.3 s article pages. The old code needed
        # 4 x (0.4 + 40 x 0.3) = ~50 s here; now the wait is one feed's latency.
        self.feeds(**{n: dict(delay=0.4, n=40, adelay=0.3) for n in ("A", "B", "C", "D")})
        t = time.time()
        items = news.all_headlines()
        took = time.time() - t
        self.assertEqual(len(items), 160)
        self.assertLess(took, 1.5, f"cold fetch took {took:.2f}s")
        self.assertEqual([i["source"] for i in items[:1]], ["A"])                  # FEEDS order kept
        self.assertTrue(all(i["ts"] > 0 for i in items))                            # pubDate parsed

    def test_photos_arrive_in_the_background(self):
        self.feeds(A=dict(n=8, adelay=0.05))
        items = news.all_headlines()
        deadline = time.time() + 15          # generous: a loaded machine runs the background lookups late
        while time.time() < deadline and not all(i["image"] for i in items):
            time.sleep(0.05)
        self.assertTrue(all(i["image"] == "https://img.example/p.jpg" for i in items))   # served as http, upgraded for the CSP
        self.assertEqual(sum(v for k, v in self.pub.hits.items() if k.startswith("/article")), 8)

    def test_warm_cache_is_instant_and_a_stale_one_refreshes_behind_the_request(self):
        self.feeds(A=dict(delay=0.5, n=5))
        news.all_headlines()
        news.TTL_SECONDS = 0                                  # everything is now stale
        t = time.time()
        items = news.all_headlines()                          # must not wait for the 0.5 s feed
        self.assertLess(time.time() - t, 0.2)
        self.assertEqual(len(items), 5)
        deadline = time.time() + 3
        while time.time() < deadline and self.pub.hits.get("/feed?A", 0) < 2:
            time.sleep(0.05)
        self.assertEqual(self.pub.hits["/feed?A"], 2)         # the background refresh ran

    def test_one_hanging_feed_does_not_hold_the_tab_hostage(self):
        news.FEEDS = {"ok1": self.pub.url("/feed", tag="ok1", n=3), "hang": self.pub.url("/hang"),
                      "ok2": self.pub.url("/feed", tag="ok2", n=4)}
        t = time.time()
        items = news.all_headlines()
        took = time.time() - t
        self.assertEqual(sorted({i["source"] for i in items}), ["ok1", "ok2"])
        self.assertLess(took, 2.0, f"took {took:.2f}s")        # bounded by the 1 s read timeout, not 30 s

    def test_a_failing_feed_keeps_its_last_good_copy(self):
        self.feeds(A=dict(n=6))
        self.assertEqual(len(news.all_headlines()), 6)
        self.pub.mode["A"] = "bad"
        self.assertEqual(len(news.all_headlines(force=True)), 6)

    def test_simultaneous_cold_requests_share_one_download_and_all_get_items(self):
        self.feeds(A=dict(delay=0.4, n=5))
        results = []
        threads = [threading.Thread(target=lambda: results.append(len(news.all_headlines()))) for _ in range(6)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(results, [5] * 6)
        self.assertEqual(self.pub.hits["/feed?A"], 1)

    def test_warm_fills_the_cache_without_blocking(self):
        self.feeds(A=dict(delay=0.3, n=4))
        t = time.time()
        news.warm()
        self.assertLess(time.time() - t, 0.15)
        deadline = time.time() + 3
        while time.time() < deadline and "A" not in news._FEED_CACHE:
            time.sleep(0.05)
        self.assertEqual(len(news.all_headlines()), 4)
        self.assertEqual(self.pub.hits["/feed?A"], 1)


if __name__ == "__main__":
    unittest.main()
