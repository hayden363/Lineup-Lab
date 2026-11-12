"""Tests for engine/imgshrink.py and the /api/img proxy that uses it.

No network: requests.get is replaced with a fake that returns generated pictures.

    .venv/bin/python -m unittest tests.test_image_proxy -v
"""
import io
import os
import tempfile
import threading
import time
import unittest
from unittest import mock

from PIL import Image

from engine.imgshrink import MAX_WIDTH, shrink


def make_image(width, height, fmt="JPEG", mode="RGB"):
    # Noise-like content so the file is realistically large (flat colour compresses to nothing).
    im = Image.effect_noise((width, height), 90).convert(mode)
    buf = io.BytesIO()
    im.save(buf, format=fmt)
    return buf.getvalue()


class Shrink(unittest.TestCase):
    def test_a_wide_photo_becomes_a_smaller_webp_at_the_max_width(self):
        data = make_image(1920, 1080)
        out, ctype = shrink(data, "image/jpeg")
        self.assertEqual(ctype, "image/webp")
        self.assertLess(len(out), len(data))
        w, h = Image.open(io.BytesIO(out)).size
        self.assertEqual(w, MAX_WIDTH)
        self.assertAlmostEqual(h / w, 1080 / 1920, places=2)       # aspect ratio kept

    def test_a_small_image_is_returned_untouched(self):
        data = make_image(100, 100)
        self.assertLess(len(data), 60_000)
        self.assertEqual(shrink(data, "image/jpeg"), (data, "image/jpeg"))

    def test_gif_and_svg_are_never_touched(self):
        for ctype in ("image/gif", "image/svg+xml", "image/x-icon"):
            self.assertEqual(shrink(b"not decoded", ctype), (b"not decoded", ctype))

    def test_garbage_bytes_fall_back_to_the_original(self):
        self.assertEqual(shrink(b"\x00" * 100, "image/jpeg"), (b"\x00" * 100, "image/jpeg"))

    def test_png_with_transparency_keeps_it(self):
        im = Image.effect_noise((900, 900), 90).convert("RGBA")
        im.putalpha(Image.linear_gradient("L").resize((900, 900)))
        buf = io.BytesIO()
        im.save(buf, format="PNG")
        out, ctype = shrink(buf.getvalue(), "image/png")
        self.assertEqual(ctype, "image/webp")
        self.assertEqual(Image.open(io.BytesIO(out)).mode, "RGBA")

    def test_a_result_that_is_not_smaller_is_not_used(self):
        data = make_image(700, 700)
        with mock.patch("PIL.Image.Image.save", side_effect=lambda fp, **kw: fp.write(b"x" * (len(data) + 10))):
            self.assertEqual(shrink(data, "image/jpeg"), (data, "image/jpeg"))

    def test_an_oversized_pixel_count_is_refused_without_decoding(self):
        data = make_image(700, 700)
        with mock.patch("engine.imgshrink.MAX_PIXELS", 1000):
            self.assertEqual(shrink(data, "image/jpeg"), (data, "image/jpeg"))


class FakeResponse:
    def __init__(self, content, content_type="image/jpeg", status=200):
        self.content, self.status = content, status
        self.headers = {"Content-Type": content_type}

    def raise_for_status(self):
        if self.status >= 400:
            raise RuntimeError(f"HTTP {self.status}")


class Proxy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        import server
        cls.server = server
        cls.client = TestClient(server.app, raise_server_exceptions=False)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.object(self.server, "_IMG_PROXY_CACHE_DIR", self.tmp.name)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.server._IMG_PROXY_FAILED.clear()
        self.addCleanup(self.server._IMG_PROXY_FAILED.clear)

    def get(self, url):
        return self.client.get("/api/img", params={"url": url})

    def test_the_two_news_photo_hosts_are_now_allowed(self):
        for host in ("www.profootballrumors.com", "nbcsports.brightspotcdn.com"):
            self.assertIn(host, self.server._IMG_PROXY_ALLOWED_HOSTS)

    def test_other_hosts_are_still_refused(self):
        for url in ("https://evil.example.com/a.jpg", "https://profootballrumors.com/a.jpg",
                    "https://nbcsports.brightspotcdn.com.evil.com/a.jpg", "file:///etc/passwd"):
            with mock.patch.object(self.server.requests, "get") as g:
                self.assertEqual(self.get(url).status_code, 400, url)
            g.assert_not_called()

    def test_a_big_news_photo_is_sent_shrunk_and_as_webp(self):
        big = make_image(1920, 1080)
        with mock.patch.object(self.server.requests, "get", return_value=FakeResponse(big)):
            r = self.get("https://nbcsports.brightspotcdn.com/a/b.jpg")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["content-type"], "image/webp")
        self.assertLess(len(r.content), len(big))
        self.assertEqual(r.headers["cache-control"], "public, max-age=86400")

    def test_the_second_request_comes_from_disk_without_fetching(self):
        big = make_image(1600, 900)
        url = "https://www.profootballrumors.com/x.jpg"
        with mock.patch.object(self.server.requests, "get", return_value=FakeResponse(big)) as g:
            first = self.get(url)
            second = self.get(url)
        self.assertEqual(g.call_count, 1)
        self.assertEqual(first.content, second.content)
        self.assertEqual(second.headers["content-type"], "image/webp")

    def test_simultaneous_requests_for_one_photo_fetch_it_once(self):
        big = make_image(1600, 900)
        url = "https://nbcsports.brightspotcdn.com/same.jpg"
        calls, lock = [0], threading.Lock()

        def slow_get(*a, **k):
            with lock:
                calls[0] += 1
            time.sleep(0.2)
            return FakeResponse(big)
        statuses = []

        def worker():
            statuses.append(self.get(url).status_code)
        with mock.patch.object(self.server.requests, "get", side_effect=slow_get):
            ts = [threading.Thread(target=worker) for _ in range(8)]
            for t in ts:
                t.start()
            for t in ts:
                t.join(timeout=30)
        self.assertEqual(calls[0], 1)
        self.assertEqual(statuses, [200] * 8)

    def test_a_small_png_logo_is_passed_through_unchanged(self):
        small = make_image(60, 60, fmt="PNG")
        with mock.patch.object(self.server.requests, "get", return_value=FakeResponse(small, "image/png")):
            r = self.get("https://a.espncdn.com/logo.png")
        self.assertEqual(r.headers["content-type"], "image/png")
        self.assertEqual(r.content, small)

    def test_a_failed_fetch_is_502_and_is_not_retried_for_a_moment(self):
        url = "https://www.profootballrumors.com/broken.jpg"
        with mock.patch.object(self.server.requests, "get", side_effect=RuntimeError("down")) as g:
            self.assertEqual(self.get(url).status_code, 502)
            self.assertEqual(self.get(url).status_code, 502)
        self.assertEqual(g.call_count, 1)

    def test_a_failed_fetch_is_retried_after_the_pause(self):
        url = "https://www.profootballrumors.com/flaky.jpg"
        with mock.patch.object(self.server.requests, "get", side_effect=RuntimeError("down")):
            self.assertEqual(self.get(url).status_code, 502)
        self.server._IMG_PROXY_FAILED.clear()
        with mock.patch.object(self.server.requests, "get", return_value=FakeResponse(make_image(100, 100))):
            self.assertEqual(self.get(url).status_code, 200)

    def test_a_non_image_response_is_refused(self):
        with mock.patch.object(self.server.requests, "get", return_value=FakeResponse(b"<html>", "text/html")):
            self.assertEqual(self.get("https://www.profootballrumors.com/p").status_code, 502)

    def test_redirects_are_still_not_followed(self):
        with mock.patch.object(self.server.requests, "get", return_value=FakeResponse(b"", status=302)) as g:
            self.get("https://nbcsports.brightspotcdn.com/r.jpg")
        self.assertIs(g.call_args.kwargs.get("allow_redirects"), False)

    def test_an_original_over_the_fetch_cap_is_refused(self):
        with mock.patch.object(self.server, "_IMG_PROXY_MAX_BYTES", 1000), \
                mock.patch.object(self.server.requests, "get", return_value=FakeResponse(make_image(700, 700))):
            self.assertEqual(self.get("https://a.espncdn.com/huge.jpg").status_code, 502)

    def test_no_half_written_files_are_left_behind(self):
        with mock.patch.object(self.server.requests, "get", return_value=FakeResponse(make_image(1600, 900))):
            self.get("https://nbcsports.brightspotcdn.com/clean.jpg")
        self.assertEqual([n for n in os.listdir(self.tmp.name) if n.endswith(".tmp")], [])


if __name__ == "__main__":
    unittest.main()
