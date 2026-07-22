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
import { renderFormattedPayloadDate } from "@plane/utils";
// components
import { DataTable } from "@/components/analytics/insight-table/data-table";
// services
import { AnalyticsService } from "@/services/analytics.service";
// local imports
import { buildDeliveryColumns } from "./columns";
import { buildDeliveryRows, type TLabelDetail } from "./utils";

const analyticsService = new AnalyticsService();

export const WorkspaceDeliveryRoot = observer(function WorkspaceDeliveryRoot() {
  // router
  const { workspaceSlug } = useParams();
  const { t } = useTranslation();
  // the target_date filter is inclusive (target_date <= value), so use yesterday
  // as the cutoff — a work item due today is not yet overdue.
  const overdueCutoff = useMemo(() => {
    const yesterday = new Date();
    yesterday.setDate(yesterday.getDate() - 1);
    return renderFormattedPayloadDate(yesterday) ?? "";
  }, []);

  // per-label counts segmented by state group (gives completed + total counts)
  const { data: stateData, isLoading: isStateLoading } = useSWR(
    workspaceSlug ? `workspace-delivery-state-${workspaceSlug.toString()}` : null,
    workspaceSlug ? () => analyticsService.getLabelStateDistribution(workspaceSlug.toString()) : null
  );
  // per-label counts of open work items whose target date has passed
  const { data: overdueData, isLoading: isOverdueLoading } = useSWR(
    workspaceSlug && overdueCutoff ? `workspace-delivery-overdue-${workspaceSlug.toString()}-${overdueCutoff}` : null,
    workspaceSlug && overdueCutoff
      ? () => analyticsService.getLabelOverdueDistribution(workspaceSlug.toString(), overdueCutoff)
      : null
  );

  const isLoading = isStateLoading || isOverdueLoading;
  const labelDetails: TLabelDetail[] | undefined = stateData?.extras?.label_details;

  const rows = useMemo(
    () => buildDeliveryRows(stateData?.distribution, overdueData?.distribution, labelDetails),
    [stateData?.distribution, overdueData?.distribution, labelDetails]
  );
  const columns = useMemo(() => buildDeliveryColumns({ t }), [t]);

  if (isLoading) {
    return (
      <div className="grid h-full w-full place-items-center">
        <Spinner />
      </div>
    );
  }

  if (rows.length === 0) {
    return (
      <div className="grid h-full w-full place-items-center">
        <EmptyStateCompact
          assetKey="unknown"
          assetClassName="size-20"
          title={t("workspace_delivery.empty_state.title")}
        />
      </div>
    );
  }

  return (
    <div className="px-page-x py-4">
      <DataTable columns={columns} data={rows} searchPlaceholder={t("workspace_delivery.search_placeholder")} />
    </div>
  );
});
