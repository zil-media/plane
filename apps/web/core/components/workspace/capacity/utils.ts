/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { orderBy } from "lodash-es";
import type { TStateGroups } from "@plane/types";

// state groups that count towards a member's "open" workload
export const OPEN_STATE_GROUPS: TStateGroups[] = ["backlog", "unstarted", "started"];

// TODO: tunable placeholder — number of open work items above which a member is flagged as overloaded
export const CAPACITY_OVERLOAD_THRESHOLD = 10;

export type TCapacityStateCounts = Record<TStateGroups, number>;

export type TCapacityRow = {
  memberId: string;
  counts: TCapacityStateCounts;
  openCount: number;
  isOverloaded: boolean;
};

// shape of a single distribution entry returned by the analytics endpoint
type TDistributionEntry = {
  dimension: string;
  segment: TStateGroups | null;
  count: number;
};

type TDistribution = Record<string, TDistributionEntry[]>;

const EMPTY_COUNTS = (): TCapacityStateCounts => ({
  backlog: 0,
  unstarted: 0,
  started: 0,
  completed: 0,
  cancelled: 0,
});

/**
 * Builds a capacity row per member, unioning the analytics distribution against the
 * full member roster so members with zero issues still appear (seeded with zeros).
 * @param distribution analytics distribution keyed by assignee id
 * @param memberIds full workspace member roster
 * @returns rows sorted by open work-item count (descending)
 */
export const buildCapacityRows = (distribution: TDistribution | undefined, memberIds: string[]): TCapacityRow[] => {
  const rows: TCapacityRow[] = memberIds.map((memberId) => {
    const counts = EMPTY_COUNTS();
    const entries = distribution?.[memberId] ?? [];
    entries.forEach((entry) => {
      if (entry.segment && entry.segment in counts) {
        counts[entry.segment] += entry.count ?? 0;
      }
    });
    const openCount = OPEN_STATE_GROUPS.reduce((sum, group) => sum + counts[group], 0);
    return {
      memberId,
      counts,
      openCount,
      isOverloaded: openCount > CAPACITY_OVERLOAD_THRESHOLD,
    };
  });

  // busiest first; orderBy (not .sort/.toSorted) keeps oxlint + tsc lib happy
  return orderBy(rows, ["openCount"], ["desc"]);
};
