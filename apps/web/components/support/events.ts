/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// Any component can open the support surfaces without prop drilling (help menu, error pages, empty states).
export const OPEN_BUG_REPORTER_EVENT = "zil:open-bug-reporter";
export const OPEN_FEATURE_SUGGEST_EVENT = "zil:open-feature-suggest";

export function openBugReporter() {
  window.dispatchEvent(new CustomEvent(OPEN_BUG_REPORTER_EVENT));
}

export function openFeatureSuggest() {
  window.dispatchEvent(new CustomEvent(OPEN_FEATURE_SUGGEST_EVENT));
}
