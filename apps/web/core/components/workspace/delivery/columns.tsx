/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { ColumnDef } from "@tanstack/react-table";
import { Info } from "lucide-react";
// plane imports
import type { TTranslationStore } from "@plane/i18n";
import { Tooltip } from "@plane/propel/tooltip";
import { Badge } from "@plane/ui";
// local imports
import type { TDeliveryRow } from "./utils";

type TBuildColumnsArgs = {
  t: TTranslationStore["t"];
};

// on-time rate at/above this threshold reads as healthy, below reads as at-risk
const ON_TIME_RATE_WARNING_THRESHOLD = 0.8;

export const buildDeliveryColumns = ({ t }: TBuildColumnsArgs): ColumnDef<TDeliveryRow>[] => [
  {
    id: "label",
    accessorFn: (row) => row.labelName,
    header: () => <div className="text-left">{t("workspace_delivery.columns.deliverable_type")}</div>,
    cell: ({ row }) => (
      <div className="flex items-center gap-2 text-left">
        <span
          className="h-2.5 w-2.5 flex-shrink-0 rounded-full"
          style={{ backgroundColor: row.original.labelColor && row.original.labelColor !== "" ? row.original.labelColor : "#000" }}
        />
        <span className="break-words text-secondary">{row.original.labelName}</span>
      </div>
    ),
  },
  {
    id: "completed",
    header: () => <div className="text-right">{t("workspace_delivery.columns.completed")}</div>,
    cell: ({ row }) => <div className="text-right">{row.original.completedCount}</div>,
  },
  {
    id: "overdue",
    header: () => <div className="text-right">{t("workspace_delivery.columns.overdue")}</div>,
    cell: ({ row }) => (
      <div className="text-right">
        <span className={row.original.overdueCount > 0 ? "font-semibold text-danger-primary" : undefined}>
          {row.original.overdueCount}
        </span>
      </div>
    ),
  },
  {
    id: "total",
    header: () => <div className="text-right">{t("workspace_delivery.columns.total")}</div>,
    cell: ({ row }) => <div className="text-right text-secondary">{row.original.totalCount}</div>,
  },
  {
    id: "on_time_rate",
    header: () => (
      <div className="flex items-center justify-end gap-1 text-right">
        {t("workspace_delivery.columns.on_time_rate")}
        <Tooltip tooltipContent={t("workspace_delivery.on_time_rate_tooltip")}>
          <Info className="h-3 w-3 text-tertiary" />
        </Tooltip>
      </div>
    ),
    cell: ({ row }) => {
      const { onTimeRate } = row.original;
      if (onTimeRate === null) {
        return (
          <div className="flex justify-end">
            <Badge variant="neutral" size="sm">
              {t("workspace_delivery.no_data")}
            </Badge>
          </div>
        );
      }
      const percentage = Math.round(onTimeRate * 100);
      return (
        <div className="flex justify-end">
          <Badge variant={onTimeRate >= ON_TIME_RATE_WARNING_THRESHOLD ? "success" : "warning"} size="sm">
            {percentage}%
          </Badge>
        </div>
      );
    },
  },
];
