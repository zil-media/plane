/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useMemo } from "react";
import { observer } from "mobx-react";
import { useParams } from "next/navigation";
import useSWR from "swr";
// plane imports
import { useTranslation } from "@plane/i18n";
import { EmptyStateCompact } from "@plane/propel/empty-state";
import { Spinner } from "@plane/ui";
// components
import { DataTable } from "@/components/analytics/insight-table/data-table";
// hooks
import { useMember } from "@/hooks/store/use-member";
// services
import { AnalyticsService } from "@/services/analytics.service";
// local imports
import { buildCapacityColumns } from "./columns";
import { buildCapacityRows } from "./utils";

const analyticsService = new AnalyticsService();

export const WorkspaceCapacityRoot = observer(function WorkspaceCapacityRoot() {
  // router
  const { workspaceSlug } = useParams();
  const { t } = useTranslation();
  // store hooks
  const {
    getUserDetails,
    workspace: { workspaceMemberIds },
  } = useMember();
  // fetch assignee state distribution
  const { data, isLoading } = useSWR(
    workspaceSlug ? `workspace-capacity-${workspaceSlug.toString()}` : null,
    workspaceSlug ? () => analyticsService.getAssigneeStateDistribution(workspaceSlug.toString()) : null
  );
  // derived values
  const memberIds = useMemo(() => workspaceMemberIds ?? [], [workspaceMemberIds]);
  const rows = useMemo(() => buildCapacityRows(data?.distribution, memberIds), [data?.distribution, memberIds]);
  const columns = useMemo(() => buildCapacityColumns({ t, getUserDetails }), [t, getUserDetails]);

  if (isLoading || !workspaceMemberIds) {
    return (
      <div className="grid h-full w-full place-items-center">
        <Spinner />
      </div>
    );
  }

  if (memberIds.length === 0) {
    return (
      <div className="grid h-full w-full place-items-center">
        <EmptyStateCompact
          assetKey="unknown"
          assetClassName="size-20"
          title={t("workspace_capacity.empty_state.title")}
        />
      </div>
    );
  }

  return (
    <div className="px-page-x py-4">
      <DataTable columns={columns} data={rows} searchPlaceholder={t("workspace_capacity.search_placeholder")} />
    </div>
  );
});
