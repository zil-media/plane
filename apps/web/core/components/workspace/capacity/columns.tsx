/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { ColumnDef } from "@tanstack/react-table";
import { UserRound } from "lucide-react";
// plane imports
import type { TTranslationStore } from "@plane/i18n";
import type { IUserLite } from "@plane/types";
import { Avatar, Badge } from "@plane/ui";
import { getFileURL } from "@plane/utils";
// local imports
import type { TCapacityRow } from "./utils";

type TBuildColumnsArgs = {
  t: TTranslationStore["t"];
  getUserDetails: (userId: string) => IUserLite | undefined;
};

export const buildCapacityColumns = ({ t, getUserDetails }: TBuildColumnsArgs): ColumnDef<TCapacityRow>[] => [
  {
    id: "member",
    accessorFn: (row) => getUserDetails(row.memberId)?.display_name ?? "",
    header: () => <div className="text-left">{t("workspace_capacity.columns.member")}</div>,
    cell: ({ row }) => {
      const member = getUserDetails(row.original.memberId);
      const displayName = member?.display_name ?? "";
      return (
        <div className="flex items-center gap-2 text-left">
          {member?.avatar_url ? (
            <Avatar name={displayName} src={getFileURL(member.avatar_url)} size={24} shape="circle" />
          ) : (
            <div className="flex h-6 w-6 flex-shrink-0 items-center justify-center overflow-hidden rounded-full bg-layer-1 capitalize">
              {displayName ? displayName[0] : <UserRound className="text-secondary" size={12} />}
            </div>
          )}
          <span className="break-words text-secondary">{displayName}</span>
        </div>
      );
    },
  },
  {
    id: "backlog",
    header: () => <div className="text-right">{t("workspace_capacity.columns.backlog")}</div>,
    cell: ({ row }) => <div className="text-right">{row.original.counts.backlog}</div>,
  },
  {
    id: "unstarted",
    header: () => <div className="text-right">{t("workspace_capacity.columns.unstarted")}</div>,
    cell: ({ row }) => <div className="text-right">{row.original.counts.unstarted}</div>,
  },
  {
    id: "started",
    header: () => <div className="text-right">{t("workspace_capacity.columns.started")}</div>,
    cell: ({ row }) => <div className="text-right">{row.original.counts.started}</div>,
  },
  {
    id: "completed",
    header: () => <div className="text-right">{t("workspace_capacity.columns.completed")}</div>,
    cell: ({ row }) => <div className="text-right">{row.original.counts.completed}</div>,
  },
  {
    id: "cancelled",
    header: () => <div className="text-right">{t("workspace_capacity.columns.cancelled")}</div>,
    cell: ({ row }) => <div className="text-right">{row.original.counts.cancelled}</div>,
  },
  {
    id: "open",
    header: () => <div className="text-right">{t("workspace_capacity.columns.open")}</div>,
    cell: ({ row }) => <div className="text-right font-semibold text-primary">{row.original.openCount}</div>,
  },
  {
    id: "status",
    header: () => <div className="text-right" />,
    cell: ({ row }) => (
      <div className="flex justify-end">
        <Badge variant={row.original.isOverloaded ? "destructive" : "neutral"} size="sm">
          {row.original.isOverloaded ? t("workspace_capacity.overloaded") : t("workspace_capacity.ok")}
        </Badge>
      </div>
    ),
  },
];
