// sw.js — onnow service worker 2026-06-22 (network-first shell)
const CACHE = "onnow-2026-06-22";
const SHELL = ["./", "./index.html", "./manifest.webmanifest", "./icon-192.png", "./icon-512.png"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", e => {
  e.waitUntil(
    caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", e => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);

  // Data: always fresh from network.
  if (/\.json(\?|$)/.test(url.pathname + url.search)) return;

  // App page / HTML: network-first so new versions show up immediately.
  if (req.mode === "navigate" || url.pathname.endsWith("/") || url.pathname.endsWith("index.html")) {
    e.respondWith(
      fetch(req).then(res => {
        const copy = res.clone();
        caches.open(CACHE).then(c => c.put("./index.html", copy)).catch(() => {});
        return res;
      }).catch(() => caches.match(req).then(h => h || caches.match("./index.html")))
    );
    return;
  }

  // Other shell assets: cache-first, then network.
  e.respondWith(
    caches.match(req).then(hit => hit || fetch(req).then(res => {
      const copy = res.clone();
      caches.open(CACHE).then(c => c.put(req, copy)).catch(() => {});
      return res;
    }))
  );
});

self.addEventListener("push", e => {
  let data = { title: "On Now", body: "" };
  try { if (e.data) data = Object.assign(data, e.data.json()); } catch (_) {
    try { data.body = e.data ? e.data.text() : ""; } catch (__) {}
  }
  e.waitUntil(self.registration.showNotification(String(data.title || "On Now"), {
    body: String(data.body || ""), tag: String(data.tag || "onnow"),
    icon: "./icon-192.png", badge: "./icon-192.png", renotify: true, data: { url: "./" }
  }));
});

self.addEventListener("notificationclick", e => {
  e.notification.close();
  e.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then(list => {
    for (const c of list) { if ("focus" in c) return c.focus(); }
    return self.clients.openWindow("./");
  }));
});
