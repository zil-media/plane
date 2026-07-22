/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

export type TIntake = {
  readonly id: string | undefined;
  name: string | undefined;
  description: string | undefined;
  is_default: boolean | undefined;
  project: string | undefined;
  workspace: string | undefined;
  pending_issue_count: number | undefined;
};
