/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { TBugReportDetail, TFeatureRequestDetail, TProgressEntry } from "@/services/support.service";
import { bugWasAnswered, bugWasDerived } from "./phase";

/**
 * The journey of a report / suggestion as a line of phases. Everything comes from timestamps the
 * records already have: nothing is invented here, only ordered.
 */

export type TPhaseState = "done" | "active" | "pending";

/** A translatable label; `note` is the agent's own text, appended as-is. */
export type TLabel = { key: string; params?: Record<string, string>; note?: string };

export type TPhaseStep = { label: TLabel; at?: string | null; waiting?: boolean };

export type TTrackPhase = {
  key: string;
  label: TLabel;
  state: TPhaseState;
  at?: string | null;
  sub?: TPhaseStep[];
  /** Waits on the person who asked (needs_info): "your turn" accent. */
  waiting?: boolean;
  href?: string;
  countdown?: boolean;
};

export type TTrack = {
  phases: TTrackPhase[];
  /** Terminal or frozen state, shown above (or instead of) the line. */
  banner?: { tone: "muted" | "danger" | "info"; label: TLabel; note?: string };
};

const k = (key: string, params?: Record<string, string>): TLabel => ({ key, params });

/** The agent's progress log as sub-steps; same contract for a bug diagnosis and a feature build. */
function progressSteps(progress: TProgressEntry[] | undefined, claimedAt?: string | null, active?: boolean) {
  const steps: TPhaseStep[] = (progress ?? []).map((entry) => ({
    label: { key: `helpdesk.progress.${entry.phase}`, note: entry.note || undefined },
    at: entry.at,
    waiting: entry.phase === "dudas",
  }));
  // Claimed but silent: "working on it" beats a mute phase.
  if (active && steps.length === 0) steps.push({ label: k("helpdesk.track.working"), at: claimedAt ?? null });
  return steps;
}

export function computeBugTrack(bug: TBugReportDetail): TTrack {
  // A handover, not an ending: the line says so and keeps pulsing.
  if (bugWasDerived(bug)) {
    return {
      phases: [
        { key: "received", label: k("helpdesk.track.bug.received"), state: "done", at: bug.created_at },
        { key: "derived", label: k("helpdesk.track.bug.derived"), state: "done", at: bug.resolved_at },
        { key: "feature", label: k("helpdesk.track.bug.continues"), state: "active" },
      ],
      banner: { tone: "info", label: k("helpdesk.track.bug.derived_banner") },
    };
  }

  // Closed: no fake line, just the closure said straight.
  if (bug.status === "dismissed" || bug.status === "archived") {
    const key = bugWasAnswered(bug)
      ? "helpdesk.track.bug.answered_banner"
      : bug.status === "dismissed"
        ? "helpdesk.track.bug.dismissed_banner"
        : "helpdesk.track.bug.archived_banner";
    return { phases: [], banner: { tone: bugWasAnswered(bug) ? "info" : "muted", label: k(key) } };
  }

  const rank = { open: 1, in_progress: 2, fixed: 3, resolved: 4 }[bug.status];
  const diagnosis: TPhaseState = rank > 2 ? "done" : rank === 2 ? "active" : "pending";
  return {
    phases: [
      { key: "received", label: k("helpdesk.track.bug.received"), state: "done", at: bug.created_at },
      {
        key: "diagnosis",
        label: k("helpdesk.track.bug.diagnosis"),
        state: diagnosis,
        at: rank >= 2 ? bug.claimed_at : null,
        sub: progressSteps(bug.progress, bug.claimed_at, diagnosis === "active"),
      },
      {
        key: "fixed",
        label: k("helpdesk.track.bug.fixed"),
        state: rank >= 3 ? "done" : "pending",
        at: bug.fixed_at,
        countdown: bug.status === "fixed",
      },
      {
        key: "published",
        label: k("helpdesk.track.bug.published"),
        state: rank >= 4 ? "done" : "pending",
        at: bug.resolved_at,
      },
    ],
  };
}

const FEATURE_RANK: Partial<Record<TFeatureRequestDetail["status"], number>> = {
  submitted: 1,
  spec_running: 1,
  needs_info: 1,
  spec_ready: 2,
  approved: 3,
  building: 4,
  in_review: 5,
  queued: 5,
  merged: 6,
};

export function computeFeatureTrack(feature: TFeatureRequestDetail): TTrack {
  const status = feature.status;
  const frozen = status === "rejected" || status === "on_hold";
  // Frozen: drawn up to where it got (a spec means it passed the analysis) and nothing pulses.
  const rank = frozen ? (feature.spec?.generated_at ? 2 : 1) : (FEATURE_RANK[status] ?? 1);
  const build = feature.build ?? {};

  const phases: TTrackPhase[] = [
    { key: "received", label: k("helpdesk.track.feature.received"), state: "done", at: feature.created_at },
    {
      key: "analysis",
      label: k("helpdesk.track.feature.analysis"),
      state: rank > 1 || status === "needs_info" ? "done" : "active",
      at: feature.spec?.generated_at ?? null,
    },
  ];

  if (status === "needs_info") {
    phases.push({
      key: "consult",
      label: k("helpdesk.track.feature.consult"),
      state: "active",
      waiting: true,
      sub: [{ label: k("helpdesk.track.feature.consult_waiting"), waiting: true }],
    });
  }

  phases.push(
    {
      key: "waiting_approval",
      label: k("helpdesk.track.feature.waiting_approval"),
      state: rank > 2 ? "done" : status === "spec_ready" ? "active" : "pending",
    },
    {
      key: "approved",
      label: k("helpdesk.track.feature.approved"),
      state: rank >= 3 ? "done" : "pending",
      at: feature.approval?.at ?? null,
    }
  );

  const buildState: TPhaseState = rank > 4 ? "done" : status === "building" ? "active" : "pending";
  phases.push({
    key: "build",
    label: k("helpdesk.track.feature.build"),
    state: buildState,
    waiting: buildState === "active" && feature.build_blocked,
    at: buildState !== "pending" ? (build.claimed_at ?? null) : null,
    sub: progressSteps(build.progress, build.claimed_at, buildState === "active"),
  });

  if (status === "in_review")
    phases.push({
      key: "review",
      label: k("helpdesk.track.feature.review"),
      state: "active",
      at: build.in_review_at ?? null,
      href: build.pr_url || undefined,
    });
  if (status === "queued")
    phases.push({
      key: "deploy_window",
      label: k("helpdesk.track.feature.deploy_window"),
      state: "active",
      at: build.queued_at ?? null,
      countdown: true,
    });

  phases.push({
    key: "published",
    label: k("helpdesk.track.feature.published"),
    state: status === "merged" ? "done" : "pending",
    at: build.merged_at ?? null,
  });

  if (!frozen) return { phases };

  // Frozen: nothing active, and a banner that says why it doesn't move.
  for (const phase of phases) {
    if (phase.state !== "active") continue;
    phase.state = "pending";
    phase.waiting = false;
  }
  if (status === "rejected") {
    const by = feature.rejection?.by_name;
    return {
      phases,
      banner: {
        tone: "danger",
        label: by ? k("helpdesk.track.feature.rejected_by", { name: by }) : k("helpdesk.track.feature.rejected"),
        note: feature.rejection?.notes,
      },
    };
  }
  return { phases, banner: { tone: "muted", label: k("helpdesk.track.feature.on_hold") } };
}
