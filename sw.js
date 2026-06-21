// sw.js — tvguide service worker 2026-06-21
const CACHE = "tvguide-2026-06-21";
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

// JSON data always fresh from network; shell falls back to cache offline.
self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET") return;
  if (/\.json(\?|$)/.test(url.pathname + url.search)) return; // let network handle (app adds cache-bust)
  e.respondWith(
    caches.match(e.request).then(hit => hit || fetch(e.request).then(res => {
      const copy = res.clone();
      caches.open(CACHE).then(c => c.put(e.request, copy)).catch(() => {});
      return res;
    }).catch(() => caches.match("./index.html")))
  );
});

self.addEventListener("push", e => {
  let data = { title: "On Now", body: "" };
  try { if (e.data) data = Object.assign(data, e.data.json()); } catch (_) {
    try { data.body = e.data ? e.data.text() : ""; } catch (__) {}
  }
  const opts = {
    body: String(data.body || ""),
    tag: String(data.tag || "tvguide"),
    icon: "./icon-192.png",
    badge: "./icon-192.png",
    renotify: true,
    data: { url: "./" }
  };
  e.waitUntil(self.registration.showNotification(String(data.title || "On Now"), opts));
});

self.addEventListener("notificationclick", e => {
  e.notification.close();
  e.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then(list => {
      for (const c of list) { if ("focus" in c) return c.focus(); }
      return self.clients.openWindow("./");
    })
  );
});
