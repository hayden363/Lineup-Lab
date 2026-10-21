"""
Small load test for Lineup Lab. Standard library only.

    .venv/bin/python scripts/loadtest.py http://localhost:8765 --users 20 --seconds 30

Each simulated visitor loops over the signed-out read traffic a real visitor
generates (Big Board, a position tab, a player card, search, app config) with
a short think-time, and the script reports requests/second, latency
percentiles and errors per endpoint.

Point it at a local server or a staging copy. Do NOT aim it at the production
site: it is built to push the app until it slows down.
"""

import argparse
import gzip
import json
import random
import statistics
import threading
import time
import urllib.error
import urllib.request


def fetch(url, timeout=60):
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"Accept-Encoding": "gzip"}), timeout=timeout) as r:
            body = r.read()
            if r.headers.get("Content-Encoding") == "gzip":
                body = gzip.decompress(body)
            return r.status, time.perf_counter() - t0, body
    except urllib.error.HTTPError as e:
        return e.code, time.perf_counter() - t0, b""
    except Exception:
        return 0, time.perf_counter() - t0, b""


def pct(values, p):
    if not values:
        return float("nan")
    s = sorted(values)
    return s[min(len(s) - 1, int(round(p / 100 * (len(s) - 1))))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("base", help="server URL, e.g. http://localhost:8765")
    ap.add_argument("--users", type=int, default=20, help="simulated concurrent visitors")
    ap.add_argument("--seconds", type=int, default=30)
    ap.add_argument("--think", type=float, default=0.5, help="average pause between a visitor's requests (s)")
    a = ap.parse_args()
    base = a.base.rstrip("/")

    status, _, body = fetch(base + "/api/board?pos=ALL&limit=40")
    if status != 200:
        raise SystemExit(f"{base}/api/board?pos=ALL returned {status}; is the server up?")
    ids = [p["player_id"] for p in json.loads(body)["players"]]

    steps = [
        ("meta", lambda: "/api/meta"),
        ("board ALL", lambda: "/api/board?pos=ALL&limit=60"),
        ("board pos", lambda: f"/api/board?pos={random.choice(['QB', 'RB', 'WR', 'TE'])}&limit=40"),
        ("player card", lambda: f"/api/player/{random.choice(ids)}"),
        ("search", lambda: "/api/search?q=" + random.choice(["jo", "ja", "ch", "mi", "br"])),
    ]
    lat, errs, lock = {n: [] for n, _ in steps}, {n: 0 for n, _ in steps}, threading.Lock()
    stop = time.time() + a.seconds

    def visitor():
        while time.time() < stop:
            name, path = random.choice(steps)
            status, dt, _ = fetch(base + path())
            with lock:
                lat[name].append(dt)
                if status != 200:
                    errs[name] += 1
            time.sleep(random.expovariate(1.0 / a.think) if a.think > 0 else 0)

    t0 = time.time()
    threads = [threading.Thread(target=visitor, daemon=True) for _ in range(a.users)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    wall = time.time() - t0

    total = sum(len(v) for v in lat.values())
    bad = sum(errs.values())
    print(f"\n{a.users} visitors, {wall:.0f}s: {total} requests, {total / wall:.1f} req/s, {bad} errors")
    print(f"{'endpoint':12s} {'n':>6s} {'p50':>8s} {'p95':>8s} {'p99':>8s} {'max':>8s} {'err':>5s}")
    for name, _ in steps:
        v = lat[name]
        if v:
            print(f"{name:12s} {len(v):6d} {pct(v, 50) * 1000:7.0f}ms {pct(v, 95) * 1000:7.0f}ms "
                  f"{pct(v, 99) * 1000:7.0f}ms {max(v) * 1000:7.0f}ms {errs[name]:5d}")
    allv = [x for v in lat.values() for x in v]
    print(f"{'ALL':12s} {len(allv):6d} {statistics.median(allv) * 1000:7.0f}ms {pct(allv, 95) * 1000:7.0f}ms "
          f"{pct(allv, 99) * 1000:7.0f}ms {max(allv) * 1000:7.0f}ms {bad:5d}")


if __name__ == "__main__":
    main()
