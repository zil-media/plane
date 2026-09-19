/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { TConsoleEntry } from "@/services/support.service";

const MAX_ENTRIES = 200;
const MAX_ARGS = 20;
const MAX_ARG_LENGTH = 2000;
const LEVELS = ["log", "info", "warn", "error"] as const;

const buffer: TConsoleEntry[] = [];
let installed = false;

function serialize(value: unknown): string {
  let text: string;
  if (typeof value === "string") text = value;
  else if (value instanceof Error) text = `${value.name}: ${value.message}\n${value.stack ?? ""}`;
  else {
    try {
      text = JSON.stringify(value) ?? String(value);
    } catch {
      text = String(value);
    }
  }
  return text.length > MAX_ARG_LENGTH ? `${text.slice(0, MAX_ARG_LENGTH)}…` : text;
}

export function recordConsoleEntry(level: string, args: unknown[]) {
  buffer.push({ level, args: args.slice(0, MAX_ARGS).map(serialize), timestamp: new Date().toISOString() });
  if (buffer.length > MAX_ENTRIES) buffer.splice(0, buffer.length - MAX_ENTRIES);
}

/** Keeps the last console lines so a bug report can carry what the page was saying. */
export function installConsoleCapture() {
  if (installed || typeof window === "undefined") return;
  installed = true;
  for (const level of LEVELS) {
    const original = window.console[level].bind(window.console);
    window.console[level] = (...args: unknown[]) => {
      recordConsoleEntry(level, args);
      original(...args);
    };
  }
}

export function getConsoleEntries(limit = MAX_ENTRIES): TConsoleEntry[] {
  return buffer.slice(-limit);
}
