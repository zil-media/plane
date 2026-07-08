/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

/**
 * Resolve the Zil Workspace base URL. Prefer an explicit VITE_ZIL_URL; otherwise
 * derive it from the Ops host (ops.* -> workspace.*) so it works in local dev
 * (Workspace on :3000) and prod (workspace.zil.global) without build config.
 * Mirrors the resolver used by the Ops SSO sign-in screen.
 */
export function getZilWorkspaceUrl(): string {
  const envUrl = (import.meta as unknown as { env?: Record<string, string> }).env?.VITE_ZIL_URL;
  if (envUrl) return envUrl.replace(/\/+$/, "");
  if (typeof window !== "undefined") {
    const { protocol, hostname, port } = window.location;
    if (hostname === "localhost" || hostname === "127.0.0.1") return "http://localhost:3000";
    if (hostname.startsWith("ops.")) return `${protocol}//workspace.${hostname.slice(4)}`;
    return `${protocol}//${hostname}${port ? `:${port}` : ""}`;
  }
  return "";
}
