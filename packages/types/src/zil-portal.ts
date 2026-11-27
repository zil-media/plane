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
  /** uploaded to Ops, a Drive file the portal plays, or Drive's own preview (when it can't) */
  kind?: "file" | "drive" | "drive_preview";
};

/** The second of a post's video a comment points at. */
export type TZilPortalMoment = {
  media: string;
  at: number;
  /** 0:42 */
  label: string;
};

export type TZilPortalPost = {
  id: string;
  name: string;
  publish_date: string | null;
  status: TZilPortalStatus;
  /** the Ops state's color: the calendar block's bar, as in Ops' calendar */
  status_color: string | null;
  network: string | null;
  labels: { name: string; color: string }[];
  thumbnail: TZilPortalMedia | null;
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
  clients: TZilPortalClientAccess[];
};
