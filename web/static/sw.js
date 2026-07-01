/* Work Smarter — service worker. Makes the app installable + gives an offline app-shell.
 * Conservative on purpose: only GET static/shell requests are cache-backed; the API + auth are
 * always network (never cache credentialed/CSRF responses), and non-GET requests are untouched.
 */
const CACHE = "ws-shell-v1";
const SHELL = ["/", "/static/icon-192.png", "/static/icon-512.png", "/manifest.webmanifest"];

// API / auth paths — always hit the network, never served from cache.
const APP_PATHS = ["/login", "/register", "/logout", "/me", "/profile", "/dashboard",
                   "/history", "/checkin", "/forum", "/auth/config", "/health"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;                       // never touch POST/PATCH/DELETE (auth/CSRF)
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;        // don't proxy cross-origin
  if (APP_PATHS.some((p) => url.pathname === p || url.pathname.startsWith(p + "/"))) return;  // API: network only

  if (req.mode === "navigate") {                          // page loads: network-first, offline -> cached shell
    e.respondWith(fetch(req).catch(() => caches.match("/")));
    return;
  }
  e.respondWith(caches.match(req).then((r) => r || fetch(req)));  // static assets: cache-first
});
