/**
 * This app no longer registers a service worker (it ships as a client-only
 * SPA build — see apps/web/react-router.config.ts). This file used to be a
 * generated Workbox worker from a prior Next.js/PWA build; it is kept only
 * as a kill switch so browsers that still have that old worker installed
 * (registered before the migration) stop running it: the browser's periodic
 * update check fetches this same URL, finds different bytes, and installs
 * this version, which immediately unregisters itself and clears its caches
 * instead of continuing to intercept fetches and serve stale build assets.
 */
self.addEventListener("install", () => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const cacheNames = await caches.keys();
      await Promise.all(cacheNames.map((name) => caches.delete(name)));
      await self.registration.unregister();

      const clientList = await self.clients.matchAll({ type: "window" });
      for (const client of clientList) {
        client.navigate(client.url);
      }
    })()
  );
});
