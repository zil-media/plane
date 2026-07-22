/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { orderBy } from "lodash-es";
import type { TStateGroups } from "@plane/types";

export type TDeliveryRow = {
  labelId: string;
  labelName: string;
  labelColor: string;
  completedCount: number;
  overdueCount: number;
  totalCount: number;
  // completedCount / (completedCount + overdueCount); null when there is no
  // completed or overdue work item to compute a rate from.
  onTimeRate: number | null;
};

// shape of a single distribution entry returned by the analytics endpoint
// when segmented (e.g. x_axis=labels__id, segment=state__group)
type TSegmentedEntry = {
  dimension: string;
  segment: TStateGroups | null;
  count: number;
};

// shape of a single distribution entry returned by the analytics endpoint
// when unsegmented (e.g. x_axis=labels__id with extra filters, no segment)
type TCountEntry = {
  dimension: string;
  count: number;
};

type TStateDistribution = Record<string, TSegmentedEntry[]>;
type TOverdueDistribution = Record<string, TCountEntry[]>;

export type TLabelDetail = {
  labels__id: string;
  labels__name: string;
  labels__color: string;
};

/**
 * Builds a delivery row per deliverable-type label, combining the state-segmented
 * distribution (for completed + total counts) with the overdue distribution
 * (open work items whose target date has passed).
 *
 * Note: "on-time rate" here is an approximation — completed vs. currently-overdue
 * counts — because the analytics endpoint only returns aggregate counts, not
 * per-issue timestamps. It cannot tell us whether a completed item was finished
 * before or after its target date. See root.tsx for the precise backend gap.
 *
 * @param stateDistribution per-label counts segmented by state group
 * @param overdueDistribution per-label counts of open, overdue work items
 * @param labelDetails label id -> name/color lookup returned in `extras.label_details`
 * @returns rows sorted by label name
 */
export const buildDeliveryRows = (
  stateDistribution: TStateDistribution | undefined,
  overdueDistribution: TOverdueDistribution | undefined,
  labelDetails: TLabelDetail[] | undefined
): TDeliveryRow[] => {
  const labelMap = new Map<string, { name: string; color: string }>();
  (labelDetails ?? []).forEach((label) => {
    if (label.labels__id) {
      labelMap.set(label.labels__id, { name: label.labels__name, color: label.labels__color });
    }
  });

  const rows: TDeliveryRow[] = Array.from(labelMap.entries()).map(([labelId, { name, color }]) => {
    const stateEntries = stateDistribution?.[labelId] ?? [];
    const completedCount = stateEntries.find((entry) => entry.segment === "completed")?.count ?? 0;
    const totalCount = stateEntries.reduce((sum, entry) => sum + (entry.count ?? 0), 0);
    const overdueCount = overdueDistribution?.[labelId]?.[0]?.count ?? 0;

    const denominator = completedCount + overdueCount;
    const onTimeRate = denominator > 0 ? completedCount / denominator : null;

    return {
      labelId,
      labelName: name,
      labelColor: color,
      completedCount,
      overdueCount,
      totalCount,
      onTimeRate,
    };
  });

  // alphabetical by deliverable type; orderBy (not .sort/.toSorted) keeps oxlint + tsc lib happy
  return orderBy(rows, ["labelName"], ["asc"]);
};
