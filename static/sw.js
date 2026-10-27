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

const CACHE = "lineup-lab-shell-v8";
const SHELL = [
  "/", "/style.css", "/app.js", "/chat.js", "/team-themes.js", "/theme-boot.js", "/theme.js",
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
  // Only same-origin GETs belong in the shell cache: Cache.put() rejects any
  // other method, and cross-origin font/CDN requests are the browser's job.
  if (e.request.method !== "GET" || url.origin !== self.location.origin) return;

  e.respondWith(
    fetch(e.request)
      .then((res) => {
        // Clone synchronously, before the page starts reading the body. The
        // old code cloned inside caches.open().then(), by which point the
        // response stream could already be consumed and clone() threw
        // "Response body is already used", silently skipping the cache write.
        if (res.ok) {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(e.request, copy)).catch(() => {});
        }
        return res;
      })
      .catch(() => caches.match(e.request))
  );
});
