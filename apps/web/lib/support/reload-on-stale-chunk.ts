/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// A deploy replaces every hashed chunk, so a tab opened before it fails to lazy-load a component
// (`lazy(() => import(...))`) that it had not loaded yet. Route modules already reload the page
// on that failure (react-router's loadRouteModule); this does the same for component chunks,
// which Vite reports with `vite:preloadError`. At most once per 30 s, so a chunk that is really
// missing ends in the error boundary instead of a reload loop.
const LAST_RELOAD_KEY = "zil:stale-chunk-reload-at";
const MIN_INTERVAL_MS = 30_000;

let installed = false;

function lastReloadAt(): number {
  try {
    return Number(window.sessionStorage.getItem(LAST_RELOAD_KEY)) || 0;
  } catch {
    return 0; // storage blocked: the interval guard can't be kept, so treat as never reloaded
  }
}

export function installStaleChunkReload() {
  if (installed || typeof window === "undefined") return;
  installed = true;
  window.addEventListener("vite:preloadError", (event) => {
    if (Date.now() - lastReloadAt() < MIN_INTERVAL_MS) return;
    event.preventDefault();
    try {
      window.sessionStorage.setItem(LAST_RELOAD_KEY, String(Date.now()));
    } catch {
      // see lastReloadAt
    }
    window.location.reload();
  });
}
