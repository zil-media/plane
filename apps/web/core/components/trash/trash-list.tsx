/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { observer } from "mobx-react";
import useSWR from "swr";
// plane imports
import { useTranslation } from "@plane/i18n";
import { Button } from "@plane/propel/button";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import { renderFormattedDate } from "@plane/utils";
// services
import type { TTrashItemType } from "@/services/trash.service";
import { trashService } from "@/services/trash.service";

type Props = {
  workspaceSlug: string;
  projectId: string;
  type: TTrashItemType;
};

export const TrashList = observer(function TrashList(props: Props) {
  const { workspaceSlug, projectId, type } = props;
  // states
  const [restoringId, setRestoringId] = useState<string | null>(null);
  // translation
  const { t } = useTranslation();
  // fetching
  const {
    data: items,
    isLoading,
    mutate,
  } = useSWR(
    ["PROJECT_TRASH", workspaceSlug, projectId, type],
    () => trashService.list(workspaceSlug, projectId, type),
    {
      revalidateOnFocus: false,
    }
  );

  const handleRestore = async (itemId: string) => {
    setRestoringId(itemId);
    try {
      await trashService.restore(workspaceSlug, projectId, type, itemId);
      setToast({ type: TOAST_TYPE.SUCCESS, title: t("project_settings.trash.restored") });
      await mutate();
    } catch (error) {
      const message = (error as { error?: string } | undefined)?.error;
      setToast({ type: TOAST_TYPE.ERROR, title: t("project_settings.trash.restore_failed"), message });
    } finally {
      setRestoringId(null);
    }
  };

  if (isLoading) return null;

  if (!items || items.length === 0) {
    return <p className="py-10 text-center text-body-sm-regular text-tertiary">{t("project_settings.trash.empty")}</p>;
  }

  return (
    <ul className="flex flex-col divide-y divide-subtle rounded-lg border border-subtle">
      {items.map((item) => (
        <li key={item.id} className="flex items-center justify-between gap-4 px-4 py-3">
          <div className="min-w-0">
            <p className="truncate text-body-sm-medium text-primary">
              {item.sequence_id !== null && item.project_identifier
                ? `${item.project_identifier}-${item.sequence_id} `
                : ""}
              {item.name}
            </p>
            <p className="text-caption-sm-regular text-tertiary">
              {renderFormattedDate(item.deleted_at)}
              {item.deleted_by_name
                ? ` · ${t("project_settings.trash.deleted_by", { name: item.deleted_by_name })}`
                : ""}
              {` · ${t("project_settings.trash.days_left", { count: item.days_remaining })}`}
            </p>
          </div>
          <Button
            variant="secondary"
            size="sm"
            loading={restoringId === item.id}
            disabled={restoringId !== null}
            onClick={() => void handleRestore(item.id)}
          >
            {t("project_settings.trash.restore")}
          </Button>
        </li>
      ))}
    </ul>
  );
});
