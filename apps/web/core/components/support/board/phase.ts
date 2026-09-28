/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { TBugReport, TFeatureRequest, TFeatureStatus } from "@/services/support.service";

export type TTone = "neutral" | "info" | "progress" | "waiting" | "success" | "danger";
export type TSection = "needs_you" | "in_progress" | "next_deploy" | "done" | "stalled";

export type TPhase = { labelKey: string; tone: TTone };

export const TONE_DOT: Record<TTone, string> = {
  neutral: "bg-layer-3",
  info: "bg-accent-primary",
  progress: "bg-accent-primary",
  waiting: "bg-warning-primary",
  success: "bg-success-primary",
  danger: "bg-danger-primary",
};

export const TONE_CHIP: Record<TTone, string> = {
  neutral: "border-subtle bg-layer-1 text-secondary",
  info: "border-accent-strong bg-accent-subtle text-accent-primary",
  progress: "border-accent-strong bg-accent-subtle text-accent-primary",
  waiting: "border-warning-strong bg-warning-subtle text-warning-primary",
  success: "border-success-strong bg-success-subtle text-success-primary",
  danger: "border-danger-strong bg-danger-subtle text-danger-primary",
};

/** Urgency order; the last two are history and start folded. */
export const SECTION_ORDER: TSection[] = ["needs_you", "in_progress", "next_deploy", "done", "stalled"];
export const COLLAPSIBLE_SECTIONS: TSection[] = ["done", "stalled"];

/**
 * Turned into a suggestion: the report closes as "dismissed" but the idea lives on in the feature
 * queue. The status alone can't tell it from a plain dismissal, and a reopened report keeps the
 * link — so both conditions are needed.
 */
export const bugWasDerived = (bug: TBugReport) => bug.status === "dismissed" && !!bug.derived_feature_id;

/** Closed with an answer (how to do it), not dismissed: telling them "closed" would be a lie. */
export const bugWasAnswered = (bug: TBugReport) =>
  bug.status === "dismissed" && !!bug.resolved_message?.trim() && !bugWasDerived(bug);

/** The build stopped and nobody picks it up alone: it waits for an admin to relaunch or reject. */
export const isFeatureStuck = (feature: TFeatureRequest) => feature.status === "building" && feature.build_blocked;

export function bugPhase(bug: TBugReport): TPhase {
  if (bugWasDerived(bug)) return { labelKey: "helpdesk.phase.bug.became_suggestion", tone: "info" };
  if (bugWasAnswered(bug)) return { labelKey: "helpdesk.phase.bug.answered", tone: "info" };
  if (bug.blocked_at && bug.status === "open") return { labelKey: "helpdesk.phase.bug.needs_person", tone: "waiting" };
  switch (bug.status) {
    case "open":
      return { labelKey: "helpdesk.phase.bug.received", tone: "neutral" };
    case "in_progress":
      return { labelKey: "helpdesk.phase.bug.diagnosing", tone: "progress" };
    case "fixed":
      return { labelKey: "helpdesk.phase.next_deploy", tone: "success" };
    case "resolved":
      return { labelKey: "helpdesk.phase.bug.resolved", tone: "success" };
    case "dismissed":
      return { labelKey: "helpdesk.phase.bug.dismissed", tone: "neutral" };
    default:
      return { labelKey: "helpdesk.phase.bug.archived", tone: "neutral" };
  }
}

export function featurePhase(feature: TFeatureRequest): TPhase {
  switch (feature.status) {
    case "submitted":
      return { labelKey: "helpdesk.phase.feature.received", tone: "neutral" };
    case "spec_running":
      return { labelKey: "helpdesk.phase.feature.analyzing", tone: "progress" };
    case "spec_ready":
      return { labelKey: "helpdesk.phase.feature.awaiting_decision", tone: "waiting" };
    case "needs_info":
      return { labelKey: "helpdesk.phase.feature.needs_answer", tone: "waiting" };
    case "approved":
      return { labelKey: "helpdesk.phase.feature.approved", tone: "progress" };
    case "building":
      return feature.build_blocked
        ? { labelKey: "helpdesk.phase.feature.needs_review", tone: "waiting" }
        : { labelKey: "helpdesk.phase.feature.building", tone: "progress" };
    case "in_review":
      return { labelKey: "helpdesk.phase.feature.in_review", tone: "progress" };
    case "queued":
      return { labelKey: "helpdesk.phase.next_deploy", tone: "success" };
    case "merged":
      return { labelKey: "helpdesk.phase.feature.ready", tone: "success" };
    case "rejected":
      return { labelKey: "helpdesk.phase.feature.rejected", tone: "danger" };
    default:
      return { labelKey: "helpdesk.phase.feature.on_hold", tone: "neutral" };
  }
}

export type TViewer = { isAdmin: boolean; userId?: string };

export const isMyFeature = (feature: TFeatureRequest, viewer: TViewer) =>
  !!viewer.userId && feature.requested_by?.id === viewer.userId;

/** The feature waits for a decision only an admin can take. */
const waitsForAdmin = (feature: TFeatureRequest) => feature.status === "spec_ready" || isFeatureStuck(feature);

/**
 * Tracking is "mine": my suggestions and my reports. Someone else's suggestion only joins when it
 * waits for MY decision — that is my action, not their state. The whole queue lives in the other tabs.
 */
export function onMyBoard(feature: TFeatureRequest, viewer: TViewer): boolean {
  return isMyFeature(feature, viewer) || (viewer.isAdmin && waitsForAdmin(feature));
}

/** Where a row lands. Anything that is neither history nor waiting on a decision is "in progress": no row can fall off the board. */
export function bugSection(bug: TBugReport): TSection {
  // The idea keeps moving in the other queue, so it is not archived.
  if (bugWasDerived(bug)) return "in_progress";
  if (bug.status === "resolved") return "done";
  if (bug.status === "fixed") return "next_deploy";
  if (bug.status === "dismissed" || bug.status === "archived") return "stalled";
  return "in_progress";
}

export function featureSection(feature: TFeatureRequest, viewer: TViewer): TSection {
  if (feature.status === "merged") return "done";
  if (feature.status === "queued") return "next_deploy";
  if (feature.status === "rejected" || feature.status === "on_hold") return "stalled";
  if (feature.status === "needs_info" && isMyFeature(feature, viewer)) return "needs_you";
  if (viewer.isAdmin && waitsForAdmin(feature)) return "needs_you";
  // My own stuck build that I can't unblock stays visible as alive, not in the folded archive.
  return "in_progress";
}

/** Status tabs of the suggestion queue; "active" is everything still moving. */
export const FEATURE_TABS = ["active", "to_review", "in_review", "deployed", "rejected", "all"] as const;
export type TFeatureTab = (typeof FEATURE_TABS)[number];

const ACTIVE_STATUSES = new Set<TFeatureStatus>([
  "submitted",
  "spec_running",
  "spec_ready",
  "needs_info",
  "approved",
  "building",
  "in_review",
  "queued",
]);

export function featureInTab(feature: TFeatureRequest, tab: TFeatureTab): boolean {
  switch (tab) {
    case "active":
      return ACTIVE_STATUSES.has(feature.status);
    case "to_review":
      return feature.status === "spec_ready";
    case "in_review":
      return feature.status === "in_review";
    case "deployed":
      return feature.status === "merged";
    case "rejected":
      return feature.status === "rejected";
    default:
      return true;
  }
}

// Mirrors the cron of .github/workflows/agent-batch-window.yml.
const WINDOW_HOURS_UTC = [2, 15, 21];

export function nextDeployWindow(now = new Date()): Date {
  for (let dayOffset = 0; dayOffset < 2; dayOffset++) {
    for (const hour of WINDOW_HOURS_UTC) {
      const candidate = new Date(
        Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() + dayOffset, hour, 0, 0)
      );
      if (candidate > now) return candidate;
    }
  }
  return now;
}
