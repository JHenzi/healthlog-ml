// The Companion's service worker (app/pwa.py). Pages: show the saved copy at once, fetch a fresh one in the
// background, and tell the page when it's ready. Static files: kept per version. Nothing else is touched:
// the API, sign-in and every form post go straight to the server.
const VERSION = "__VERSION__";
const STATIC = `static-${VERSION}`;
const PAGES = "pages";
const AFTER_CHANGE_MS = 15000; // after a form post, the next pages come from the server, not the saved copy
let freshUntil = 0;

self.addEventListener("install", () => self.skipWaiting());

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k.startsWith("static-") && k !== STATIC).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

async function tell(message) {
  for (const client of await self.clients.matchAll({ type: "window" })) client.postMessage(message);
}

function isSignIn(url) {
  return url.pathname === "/login" || url.pathname === "/logout";
}

async function fromServer(request, path) {
  const response = await fetch(request);
  const landed = new URL(response.url || request.url);
  if (response.redirected && isSignIn(landed)) {
    await caches.delete(PAGES); // signed out or expired: no saved pages without a session
    tell({ type: "signed-out" });
    return Response.redirect(landed.href, 303);
  }
  if (response.redirected) return Response.redirect(landed.href, 303); // Safari won't show a redirected response
  if (response.ok && (response.headers.get("content-type") || "").startsWith("text/html")) {
    const cache = await caches.open(PAGES);
    await cache.put(request, response.clone());
    tell({ type: "fresh", path });
  }
  return response;
}

async function page(event, url) {
  const path = url.pathname + url.search;
  const cache = await caches.open(PAGES);
  const saved = await cache.match(event.request);
  if (!saved || Date.now() < freshUntil) {
    try {
      return await fromServer(event.request, path);
    } catch (err) {
      if (saved) return saved;
      throw err;
    }
  }
  event.waitUntil(fromServer(event.request, path).catch(() => tell({ type: "offline", path })));
  return saved;
}

async function asset(request) {
  const cache = await caches.open(STATIC);
  const saved = await cache.match(request);
  if (saved) return saved;
  const response = await fetch(request);
  if (response.ok) await cache.put(request, response.clone());
  return response;
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (request.method !== "GET") {
    freshUntil = Date.now() + AFTER_CHANGE_MS;
    if (url.pathname === "/logout") event.waitUntil(caches.delete(PAGES));
    return;
  }
  if (url.pathname.startsWith("/api/") || isSignIn(url)) return;
  if (url.pathname.startsWith("/static/")) {
    event.respondWith(asset(request));
    return;
  }
  if (request.mode === "navigate") event.respondWith(page(event, url));
});
