// Minimal service worker: caches the app shell so the page still opens
// (with stale data) offline / when reinstalling from the home screen.
// API calls (/api/*) always go to the network — we never cache live stats.
//
// Network-first for the shell itself: try the network, and only fall back
// to the cache if that actually fails (offline). A cache-first strategy
// here silently swallows every real change to the app — the browser just
// keeps serving whatever was cached the first time the service worker
// installed, no matter how many times the page reloads, since the SW
// intercepts the fetch before normal HTTP caching even gets a say. This
// still updates the cache on every successful fetch, so offline mode
// stays reasonably fresh too — it just never wins over a live network.

const CACHE = "lineup-lab-shell-v3";
const SHELL = [
  "/", "/style.css", "/app.js",
  "/icons/icon-192.png", "/icons/icon-512.png", "/icons/apple-touch-icon.png",
];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
  );
  self.clients.claim();
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (url.pathname.startsWith("/api/")) return; // never cache live data

  e.respondWith(
    fetch(e.request)
      .then((res) => {
        if (res.ok) caches.open(CACHE).then((c) => c.put(e.request, res.clone()));
        return res;
      })
      .catch(() => caches.match(e.request))
  );
});
