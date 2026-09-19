/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { TBugReport, TFeatureRequest } from "@/services/support.service";

export type TTone = "neutral" | "progress" | "waiting" | "success" | "danger";
export type TSection = "needs_you" | "in_progress" | "next_deploy" | "done" | "stalled";

export type TPhase = { labelKey: string; tone: TTone; section: TSection };

export const TONE_DOT: Record<TTone, string> = {
  neutral: "bg-layer-3",
  progress: "bg-accent-primary",
  waiting: "bg-warning-primary",
  success: "bg-success-primary",
  danger: "bg-danger-primary",
};

export const SECTION_ORDER: TSection[] = ["needs_you", "in_progress", "next_deploy", "done", "stalled"];

export function bugPhase(bug: TBugReport): TPhase {
  if (bug.blocked_at && bug.status === "open")
    return { labelKey: "helpdesk.phase.bug.needs_person", tone: "waiting", section: "stalled" };
  switch (bug.status) {
    case "open":
      return { labelKey: "helpdesk.phase.bug.received", tone: "neutral", section: "in_progress" };
    case "in_progress":
      return { labelKey: "helpdesk.phase.bug.diagnosing", tone: "progress", section: "in_progress" };
    case "fixed":
      return { labelKey: "helpdesk.phase.next_deploy", tone: "progress", section: "next_deploy" };
    case "resolved":
      return { labelKey: "helpdesk.phase.bug.resolved", tone: "success", section: "done" };
    case "dismissed":
      if (bug.derived_feature_id)
        return { labelKey: "helpdesk.phase.bug.became_suggestion", tone: "neutral", section: "done" };
      if (bug.resolved_message) return { labelKey: "helpdesk.phase.bug.answered", tone: "success", section: "done" };
      return { labelKey: "helpdesk.phase.bug.dismissed", tone: "neutral", section: "done" };
    default:
      return { labelKey: "helpdesk.phase.bug.archived", tone: "neutral", section: "done" };
  }
}

export function featurePhase(feature: TFeatureRequest): TPhase {
  switch (feature.status) {
    case "submitted":
      return { labelKey: "helpdesk.phase.feature.received", tone: "neutral", section: "in_progress" };
    case "spec_running":
      return { labelKey: "helpdesk.phase.feature.analyzing", tone: "progress", section: "in_progress" };
    case "spec_ready":
      return { labelKey: "helpdesk.phase.feature.awaiting_decision", tone: "waiting", section: "in_progress" };
    case "needs_info":
      return { labelKey: "helpdesk.phase.feature.needs_answer", tone: "waiting", section: "needs_you" };
    case "approved":
      return { labelKey: "helpdesk.phase.feature.approved", tone: "progress", section: "in_progress" };
    case "building":
      return feature.build_blocked
        ? { labelKey: "helpdesk.phase.feature.needs_review", tone: "waiting", section: "stalled" }
        : { labelKey: "helpdesk.phase.feature.building", tone: "progress", section: "in_progress" };
    case "in_review":
      return { labelKey: "helpdesk.phase.feature.in_review", tone: "progress", section: "in_progress" };
    case "queued":
      return { labelKey: "helpdesk.phase.next_deploy", tone: "progress", section: "next_deploy" };
    case "merged":
      return { labelKey: "helpdesk.phase.feature.ready", tone: "success", section: "done" };
    case "rejected":
      return { labelKey: "helpdesk.phase.feature.rejected", tone: "danger", section: "done" };
    default:
      return { labelKey: "helpdesk.phase.feature.on_hold", tone: "neutral", section: "stalled" };
  }
}

// Mirrors the cron of .github/workflows/agent-batch-window.yml.
const WINDOW_HOURS_UTC = [2, 15, 21];

/** When the next batch window ships what is already merged into agent-batch. */
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
