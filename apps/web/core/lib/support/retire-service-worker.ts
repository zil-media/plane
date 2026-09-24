/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// This app ships as a client-only SPA and never registers a service worker
// (see react-router.config.ts: ssr: false). public/sw.js is a kill switch
// left only for browsers that registered a real (Workbox) worker before this
// app dropped PWA support: that worker intercepts fetches and can serve a
// stale cached document/chunk against a codebase whose asset hashes have
// since moved on, which surfaces as React hydration errors on "/" or a
// parse error when a stale chunk is executed.
//
// The kill switch in sw.js only takes effect on that worker's own update
// check, which the browser doesn't run on every load. Unregistering here too
// means a returning user stops being controlled by it starting with their
// very next navigation, and clearing Cache Storage now means any in-page
// fetch this session that falls through to the worker's cache misses it and
// goes to the network instead of a stale response.
export async function retireLegacyServiceWorker(): Promise<void> {
  if (typeof navigator === "undefined" || !("serviceWorker" in navigator)) return;

  try {
    const registrations = await navigator.serviceWorker.getRegistrations();
    await Promise.all(registrations.map((registration) => registration.unregister()));
  } catch {
    // Best-effort cleanup; nothing to recover from if the browser refuses.
  }

  if (typeof caches === "undefined") return;

  try {
    const cacheNames = await caches.keys();
    await Promise.all(cacheNames.map((name) => caches.delete(name)));
  } catch {
    // Same as above.
  }
}
