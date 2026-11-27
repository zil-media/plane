/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { RouteConfig } from "@react-router/dev/routes";
import { index, layout, route } from "@react-router/dev/routes";

export default [
  index("./page.tsx"),
  // a brand's client portal (Zil): its calendar, its documents and the way in
  route("portal", "./portal/page.tsx"),
  route("portal/login", "./portal/login/page.tsx"),
  route("portal/invite/:token", "./portal/invite/[token]/page.tsx"),
  route("portal/:projectId", "./portal/[projectId]/page.tsx"),
  route(":workspaceSlug/:projectId", "./[workspaceSlug]/[projectId]/page.tsx"),
  layout("./issues/[anchor]/layout.tsx", [route("issues/:anchor", "./issues/[anchor]/page.tsx")]),
  // Catch-all route for 404 handling
  route("*", "./not-found.tsx"),
] satisfies RouteConfig;
