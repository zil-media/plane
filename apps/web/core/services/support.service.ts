/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { API_BASE_URL } from "@plane/constants";
// services
import { APIService } from "@/services/api.service";

export type TBugStatus = "open" | "in_progress" | "fixed" | "resolved" | "dismissed" | "archived";
export type TBugUrgency = "noise" | "low" | "medium" | "high" | "urgent";
export type TFeatureStatus =
  | "submitted"
  | "spec_running"
  | "spec_ready"
  | "needs_info"
  | "approved"
  | "building"
  | "in_review"
  | "queued"
  | "merged"
  | "rejected"
  | "on_hold";
export type TFeaturePriority = "baja" | "media" | "alta";
export type TFeatureDecision = "approve" | "reject" | "hold" | "rebuild";

export type TSupportPerson = {
  id: string;
  email: string;
  display_name: string;
  first_name: string;
  last_name: string;
};

export type TProgressEntry = { at: string; phase: string; note: string };

export type TSupportComment = {
  at: string;
  author_id: string | null;
  author_name: string;
  role: "user" | "admin" | "agent";
  text: string;
};

export type TConsoleEntry = { level: string; args: string[]; timestamp?: string };

export type TBugReport = {
  id: string;
  status: TBugStatus;
  severity: "bloqueante" | "molesto" | "sugerencia";
  source: "manual" | "auto";
  origin: string;
  urgency: TBugUrgency;
  description: string;
  url: string;
  display_title: string;
  category: string;
  plain_summary: string;
  occurrences: number;
  affected_users: number;
  blocked_at: string | null;
  blocked_reason: string;
  claimed_at: string | null;
  reported_by: TSupportPerson | null;
  workspace_slug: string | null;
  derived_feature_id: string | null;
  resolved_message: string;
  created_at: string;
  last_seen_at: string | null;
  fixed_at: string | null;
  resolved_at: string | null;
  progress?: TProgressEntry[];
  comments?: TSupportComment[];
};

export type TBugReportDetail = TBugReport & {
  user_agent: string;
  system_info: Record<string, unknown>;
  console_logs: TConsoleEntry[];
  error_type: string;
  stack_trace: string;
  attachments: { id: string; name: string; type: string; url: string }[];
  progress: TProgressEntry[];
  comments: TSupportComment[];
  admin_notes: string;
  commit_hash: string;
};

export type TFeatureSpec = {
  summary?: string;
  approach?: string;
  affected_areas?: string[];
  files_touched?: string[];
  db_changes?: string;
  risks?: string[];
  rollback?: string;
  effort?: string;
  open_questions?: string[];
  blast_radius?: "low" | "medium" | "high";
  flag_key?: string;
};

export type TFeatureBuild = {
  claimed_at?: string | null;
  blocked_at?: string | null;
  last_note?: string;
  pr_url?: string;
  progress?: TProgressEntry[];
  merged_at?: string;
  queued_at?: string;
  in_review_at?: string;
};

export type TFeatureRequest = {
  id: string;
  status: TFeatureStatus;
  title: string;
  display_title: string;
  category: string;
  plain_summary: string;
  priority: TFeaturePriority;
  blast_radius: "low" | "medium" | "high" | null;
  flag_key: string;
  requested_by: TSupportPerson | null;
  workspace_slug: string | null;
  pr_url: string | null;
  build_blocked: boolean;
  created_at: string;
  updated_at: string;
};

export type TFeatureRequestDetail = TFeatureRequest & {
  problem: string;
  desired_outcome: string;
  source_url: string;
  spec: TFeatureSpec;
  approval: { by?: string; by_name?: string; at?: string; notes?: string };
  rejection: { by_name?: string; at?: string; notes?: string };
  build: TFeatureBuild;
  comments: TSupportComment[];
};

export type TSupportMe = {
  is_admin: boolean;
  categories: string[];
  bug_agent_enabled: boolean;
  feature_agent_enabled: boolean;
  max_builds_per_week: number;
};

export type TCreateBugReport = {
  description: string;
  urgent: boolean;
  url: string;
  user_agent: string;
  viewport: { width: number; height: number };
  system_info: Record<string, unknown>;
  console_logs: TConsoleEntry[];
  attachment_ids: string[];
  workspace_slug: string;
};

export type TAutoBugReport = {
  fingerprint: string;
  error_type: string;
  message: string;
  stack: string;
  component_stack: string;
  url: string;
  system_info: Record<string, unknown>;
  console_logs: TConsoleEntry[];
  workspace_slug: string;
};

export type TCreateFeatureRequest = {
  title: string;
  problem: string;
  desired_outcome: string;
  priority: TFeaturePriority;
  source_url: string;
  attachment_ids: string[];
  workspace_slug: string;
};

export class SupportService extends APIService {
  constructor() {
    super(API_BASE_URL);
  }

  private async unwrap<T>(promise: Promise<{ data: T }>): Promise<T> {
    return promise
      .then((response) => response.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  me() {
    return this.unwrap<TSupportMe>(this.get("/api/support/me/"));
  }

  updateConfig(data: Partial<Omit<TSupportMe, "is_admin" | "categories">>) {
    return this.unwrap<TSupportMe>(this.patch("/api/support/config/", data));
  }

  enabledFlags() {
    return this.unwrap<{ enabled: string[] }>(this.get("/api/support/feature-flags/"));
  }

  createBugReport(data: TCreateBugReport) {
    return this.unwrap<TBugReport>(this.post("/api/support/bug-reports/", data));
  }

  myBugReports() {
    return this.unwrap<TBugReport[]>(this.get("/api/support/bug-reports/mine/"));
  }

  allBugReports(params: { status?: string; source?: string; blocked?: boolean } = {}) {
    return this.unwrap<TBugReport[]>(this.get("/api/support/bug-reports/", { params }));
  }

  bugReport(id: string) {
    return this.unwrap<TBugReportDetail>(this.get(`/api/support/bug-reports/${id}/`));
  }

  reopenBugReport(id: string, comment: string) {
    return this.unwrap<TBugReport>(this.post(`/api/support/bug-reports/${id}/reopen/`, { comment }));
  }

  bulkBugAction(action: "resolve" | "dismiss" | "archive" | "unblock", ids: string[], admin_notes = "") {
    return this.unwrap<{ changed: number }>(this.post("/api/support/bug-reports/bulk/", { action, ids, admin_notes }));
  }

  sendToFixer(id: string) {
    return this.unwrap<{ fired: boolean; reason?: string }>(this.post(`/api/support/bug-reports/${id}/send-to-fixer/`));
  }

  featureRequests(params: { scope?: "mine" | "all"; status?: string } = {}) {
    return this.unwrap<TFeatureRequest[]>(this.get("/api/support/feature-requests/", { params }));
  }

  featureRequest(id: string) {
    return this.unwrap<TFeatureRequestDetail>(this.get(`/api/support/feature-requests/${id}/`));
  }

  createFeatureRequest(data: TCreateFeatureRequest) {
    return this.unwrap<TFeatureRequest>(this.post("/api/support/feature-requests/", data));
  }

  commentFeatureRequest(id: string, text: string) {
    return this.unwrap<TFeatureRequest>(this.post(`/api/support/feature-requests/${id}/comments/`, { text }));
  }

  decideFeatureRequest(id: string, decision: TFeatureDecision, data: { notes?: string; flag_key?: string } = {}) {
    return this.unwrap<TFeatureRequest>(this.post(`/api/support/feature-requests/${id}/${decision}/`, data));
  }

  setFeatureFlag(id: string, enabled: boolean) {
    return this.unwrap<{ key: string; enabled: boolean }>(
      this.post(`/api/support/feature-requests/${id}/flag/`, { enabled })
    );
  }
}

export const supportService = new SupportService();
