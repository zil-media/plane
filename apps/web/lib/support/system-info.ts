/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

type TNavigatorExtras = Navigator & {
  connection?: { effectiveType?: string };
  deviceMemory?: number;
};

export function getSystemInfo(): Record<string, unknown> {
  const nav = window.navigator as TNavigatorExtras;
  const active = document.activeElement;
  return {
    language: nav.language,
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    screen: `${window.screen.width}x${window.screen.height}`,
    pixel_ratio: window.devicePixelRatio,
    connection: nav.connection?.effectiveType,
    device_memory_gb: nav.deviceMemory,
    cpu_cores: nav.hardwareConcurrency,
    online: nav.onLine,
    focused_element: active ? `${active.tagName.toLowerCase()}${active.id ? `#${active.id}` : ""}` : undefined,
    theme: document.documentElement.dataset.theme ?? document.documentElement.className,
  };
}

export function getViewport() {
  return { width: window.innerWidth, height: window.innerHeight };
}

/** The workspace the user is looking at, from the URL (`/:workspaceSlug/...`). */
export function getWorkspaceSlugFromPath(): string {
  return window.location.pathname.split("/").find(Boolean) ?? "";
}
