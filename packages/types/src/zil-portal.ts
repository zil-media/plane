/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

/** A brand's client portal (the space app's /portal screens), as its API returns it. */

export type TZilPortalBrand = {
  id: string;
  name: string;
  logo_url: string | null;
  color: string | null;
  paused: boolean;
  /** whose look the portal wears: the business unit that works the brand */
  unit?: "zil" | "meraki";
  /** a team member looking at what the client sees */
  preview?: boolean;
};

/** The four statuses the client reads instead of Ops' states (translated in the portal). */
export type TZilPortalStatus = "preparing" | "review" | "scheduled" | "published";

export type TZilPortalMedia = {
  /** an attachment's id, or "drive:<file id>" */
  id: string;
  name: string;
  type: string;
  url: string;
  /** uploaded to Ops, a Drive file Ops streams, or a Drive file Ops can't play right now */
  kind?: "file" | "drive" | "unavailable";
};

/** The second of a post's video a comment points at. */
export type TZilPortalMoment = {
  media: string;
  at: number;
  /** 0:42 */
  label: string;
};

/** What the client can still do on a post: rounds of changes left and until when. */
export type TZilPortalReview = {
  /** null: the brand sets no limit */
  rounds: number | null;
  used: number;
  left: number | null;
  /** ISO; null: no time limit */
  deadline: string | null;
  open: boolean;
  /** why it is closed */
  reason: "not_started" | "expired" | "rounds_used" | null;
};

/** A change the client is writing, not sent to the team yet. */
export type TZilPortalDraft = {
  id: string;
  text: string;
  moment: TZilPortalMoment | null;
  created_at: string;
};

export type TZilPortalPost = {
  id: string;
  name: string;
  publish_date: string | null;
  /** the hour it goes out, "HH:MM" (Ops' due time); null when none was set */
  publish_time?: string | null;
  status: TZilPortalStatus;
  /** the Ops state's color: the calendar block's bar, as in Ops' calendar */
  status_color: string | null;
  network: string | null;
  labels: { name: string; color: string }[];
  thumbnail: TZilPortalMedia | null;
  /** worked out for the posts to review and the one opened (null in the calendar's list) */
  review?: TZilPortalReview | null;
};

export type TZilPortalPostDetail = TZilPortalPost & {
  description_html: string;
  media: TZilPortalMedia[];
  links: { title: string; url: string }[];
};

export type TZilPortalComment = {
  id: string;
  html: string;
  created_at: string;
  author: string;
  avatar_url: string | null;
  is_team: boolean;
  is_mine: boolean;
  moment?: TZilPortalMoment | null;
};

export type TZilPortalDocument = {
  id: string;
  name: string;
  updated_at: string;
  /** the sub-folder it is in; null at the top of the "Cliente" folder */
  parent_id?: string | null;
  description_html?: string;
};

export type TZilPortalFolder = {
  id: string;
  name: string;
  parent_id: string | null;
};

export type TZilPortalInvite = {
  email: string;
  brand: string;
  project_id: string;
  needs_password: boolean;
  unit?: "zil" | "meraki";
};

/** The "Portal del cliente" section of the Marca tab. */
export type TZilPortalClientAccess = {
  id: string;
  email: string;
  status: "active" | "invited" | "expired" | "never";
  has_account: boolean;
  invited_at: string | null;
  last_login: string | null;
};

export type TZilPortalSettings = {
  enabled: boolean;
  paused: boolean;
  url: string;
  folder_id: string | null;
  /** rounds of changes per post and business days to ask for them from its first review (0: no limit) */
  change_rounds: number;
  change_days: number;
  clients: TZilPortalClientAccess[];
};

/** The work items of a brand whose Drive video its clients can't open (Ops' calendar marks them). */
export type TZilVideoAlerts = {
  issues: Record<string, { link_id: string; title: string; url: string }[]>;
};
