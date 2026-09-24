/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { API_BASE_URL } from "@plane/constants";
import type { TAutoBugReport } from "@/services/support.service";
import { getConsoleEntries } from "./console-capture";
import { getSystemInfo, getWorkspaceSlugFromPath } from "./system-info";

const RESEND_WINDOW_MS = 30_000;
const recentlySent = new Map<string, number>();
let installed = false;

// Noise that is not a defect: stale chunks after a deploy, browser layout warnings, extensions.
const IGNORED = [
  /ResizeObserver loop/i,
  /Failed to fetch dynamically imported module/i,
  /Importing a module script failed/i,
  /ChunkLoadError/i,
  /^Script error\.?$/i,
  /chrome-extension:\/\//i,
  /moz-extension:\/\//i,
];

function djb2(text: string): string {
  let hash = 5381;
  for (let i = 0; i < text.length; i++) hash = ((hash << 5) + hash + text.charCodeAt(i)) | 0;
  return (hash >>> 0).toString(36);
}

/** Same defect, same fingerprint: ids, numbers and query strings are stripped first. */
export function fingerprintError(errorType: string, message: string, stack: string): string {
  const topFrame = (stack.split("\n").find((line) => line.includes("at ")) ?? "")
    .replace(/\?[^):]*/g, "")
    .replace(/:\d+:\d+/g, "");
  const normalizedMessage = message
    .replace(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi, "<id>")
    .replace(/\d+/g, "<n>");
  return `fe_${djb2(`${errorType}|${normalizedMessage}|${topFrame.trim()}`)}`;
}

function isLocalhost() {
  return ["localhost", "127.0.0.1"].includes(window.location.hostname);
}

// Service calls across the app reject with the raw API error body (`error?.response?.data`,
// e.g. `{ error: "..." }` / `{ detail: "..." }`) rather than an Error, and a network failure
// with no response rejects with `undefined`. Without this, every one of those becomes an
// opaque "Unknown error" report with no way to tell what actually broke.
function extractMessage(thrown: unknown): string {
  if (typeof thrown === "string") return thrown;
  if (thrown && typeof thrown === "object") {
    const { error, detail, message } = thrown as Record<string, unknown>;
    const candidate = error ?? detail ?? message;
    if (typeof candidate === "string") return candidate;
    try {
      const json = JSON.stringify(thrown);
      if (json && json !== "{}") return json.slice(0, 500);
    } catch {
      // circular or non-serializable; fall through to the generic message
    }
  }
  return "Unknown error";
}

export function reportClientError(thrown: unknown, componentStack = "") {
  if (typeof window === "undefined" || isLocalhost()) return;
  const err = thrown instanceof Error ? thrown : new Error(extractMessage(thrown));
  const message = err.message || String(thrown);
  const stack = err.stack ?? "";
  if (IGNORED.some((pattern) => pattern.test(message) || pattern.test(stack))) return;

  const fingerprint = fingerprintError(err.name, message, stack);
  const now = Date.now();
  const last = recentlySent.get(fingerprint);
  if (last && now - last < RESEND_WINDOW_MS) return;
  recentlySent.set(fingerprint, now);

  const payload: TAutoBugReport = {
    fingerprint,
    error_type: err.name || "Error",
    message: message.slice(0, 2000),
    stack: stack.slice(0, 20000),
    component_stack: componentStack.slice(0, 20000),
    url: window.location.pathname,
    system_info: getSystemInfo(),
    console_logs: getConsoleEntries(30),
    workspace_slug: getWorkspaceSlugFromPath(),
  };
  // Plain fetch, not APIService: its 401 interceptor redirects to sign-in, and a crash on a
  // signed-out screen must not navigate anywhere. Without a session the report is just dropped.
  void fetch(`${API_BASE_URL}/api/support/bug-reports/auto/`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    keepalive: true,
  }).catch(() => undefined);
}

/** Uncaught errors and unhandled promise rejections become auto bug reports. */
export function installGlobalErrorReporting() {
  if (installed || typeof window === "undefined") return;
  installed = true;
  window.addEventListener("error", (event) => reportClientError(event.error ?? event.message));
  window.addEventListener("unhandledrejection", (event) => reportClientError(event.reason));
}
