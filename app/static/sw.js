/* Service worker: keeps the site usable without a connection.
 *
 * - Static files: from the cache, fetched once per version.
 * - Pages: from the network, saved as they load; when the network is down (or slower than a
 *   few seconds), the saved copy. The lists page then works fully offline (lists.js).
 * - Everything else (the API, live updates, form posts) goes straight to the network.
 *
 * Served at /sw.js with __VERSION__ replaced, so each release installs fresh caches.
 */
const VERSION = "__VERSION__";
const STATIC = "static-" + VERSION;
const PAGES = "pages-" + VERSION;
const CORE = [
  "/static/css/app.css?v=" + VERSION,
  "/static/js/app.js?v=" + VERSION,
  "/static/js/household.js?v=" + VERSION,
  "/static/js/lists.js?v=" + VERSION,
  "/static/js/plan.js?v=" + VERSION,
  "/static/vendor/htmx.min.js",
  "/static/vendor/Sortable.min.js",
  "/static/fonts/SchibstedGrotesk-400-900.woff2",
  "/offline",
];
const NETWORK_WAIT_MS = 3500;

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(STATIC).then((c) => c.addAll(CORE)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== STATIC && k !== PAGES).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  if (req.method === "GET" && url.pathname.startsWith("/static/")) {
    event.respondWith(fromCache(req));
  } else if (req.mode === "navigate") {
    event.respondWith(req.method === "GET" ? page(req) : postOrOffline(req));
  }
});

async function fromCache(req) {
  const hit = await caches.match(req);
  if (hit) return hit;
  const resp = await fetch(req);
  if (resp.ok) (await caches.open(STATIC)).put(req, resp.clone());
  return resp;
}

function isListsPage(url) {
  return /^\/h\/\d+$/.test(new URL(url).pathname);
}

async function page(req) {
  const cache = await caches.open(PAGES);
  const network = fetch(req).then((resp) => {
    if (resp.ok && resp.type === "basic") {
      cache.put(req, resp.clone());
      // Opening the site from the home screen starts at "/", which normally redirects to your lists.
      if (isListsPage(req.url)) cache.put("/", resp.clone());
    }
    return resp;
  });
  const quick = await Promise.race([
    network.catch(() => null),
    new Promise((resolve) => setTimeout(resolve, NETWORK_WAIT_MS, null)),
  ]);
  if (quick) return quick;
  const saved = await cache.match(req);
  if (saved) {
    network.catch(() => {}); // a slow answer still refreshes the saved copy
    return saved;
  }
  try {
    return await network;
  } catch (_) {
    return offlinePage();
  }
}

async function postOrOffline(req) {
  try {
    return await fetch(req);
  } catch (_) {
    return offlinePage();
  }
}

async function offlinePage() {
  const saved = await caches.match("/offline");
  return saved || new Response("<h1>You're offline</h1>", { headers: { "Content-Type": "text/html; charset=utf-8" } });
}

// The lists page asks for the other pages to be saved, so recipes open offline even if not visited yet.
self.addEventListener("message", (event) => {
  if (event.data && event.data.type === "warm") event.waitUntil(warm(event.data.urls || []));
});

async function warm(urls) {
  const cache = await caches.open(PAGES);
  for (const url of urls.slice(0, 300)) {
    try {
      const resp = await fetch(url, { credentials: "same-origin" });
      if (resp.ok && !resp.redirected) await cache.put(url, resp);
    } catch (_) {
      return; // offline again; try another time
    }
  }
}
