/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

export type TIssueLinkEditableFields = {
  title: string;
  url: string;
};

// Rich-card providers the backend crawler captures extra metadata for. Any
// other (or missing) provider falls back to the generic title/favicon row.
export type TIssueLinkProvider = "figma" | "google_drive";

export type TIssueLinkMetadata = {
  title?: string | null;
  favicon?: string | null;
  favicon_url?: string | null;
  url?: string;
  error?: string;
  // Present only for rich-card providers (Figma, Google Drive).
  provider?: TIssueLinkProvider;
  provider_name?: string | null;
  thumbnail?: string | null;
  author_name?: string | null;
  // ISO 8601 timestamp of the last successful crawl.
  crawled_at?: string | null;
};

export type TIssueLink = TIssueLinkEditableFields & {
  created_by_id: string;
  id: string;
  metadata: TIssueLinkMetadata;
  issue_id: string;

  //need
  created_at: Date;
};

export type TIssueLinkMap = {
  [issue_id: string]: TIssueLink;
};

export type TIssueLinkIdMap = {
  [issue_id: string]: string[];
};
