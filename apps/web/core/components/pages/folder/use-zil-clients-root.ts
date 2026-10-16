/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useCallback, useState } from "react";
import { useParams } from "next/navigation";
// plane imports
import { useTranslation } from "@plane/i18n";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
// services
import { ProjectPageService } from "@/services/page";
// store
import type { TPageInstance } from "@/store/pages/base-page";

const projectPageService = new ProjectPageService();

const ROOT_ERRORS: Record<string, string> = {
  ZIL_ROOT_NOT_PUBLIC: "page_tree.zil_client.clients_root.not_public",
  ZIL_ROOT_TOO_DEEP: "page_tree.zil_client.clients_root.too_deep",
  ZIL_ROOT_IS_CLIENT: "page_tree.zil_client.clients_root.is_client",
};

/** Mark or unmark a folder as the project's clients folder (one sub-folder per Zil client). */
export function useZilClientsRoot(page: TPageInstance) {
  const { t } = useTranslation();
  const { workspaceSlug } = useParams();
  const [isUpdating, setIsUpdating] = useState(false);
  const projectId = page.project_ids?.[0];
  const canManage = page.isFolder && !page.archived_at && !page.zil_client && page.canCurrentUserManageZilClientsRoot;

  const toggle = useCallback(async () => {
    if (!workspaceSlug || !projectId || !page.id) return;
    const next = !page.is_zil_clients_root;
    setIsUpdating(true);
    try {
      await projectPageService.setZilClientsRoot(workspaceSlug.toString(), projectId, page.id, next);
      page.mutateProperties({ is_zil_clients_root: next }, false);
      setToast({
        type: TOAST_TYPE.SUCCESS,
        title: t(
          next ? "page_tree.zil_client.clients_root.set_success" : "page_tree.zil_client.clients_root.unset_success"
        ),
      });
    } catch (error) {
      const code = (error as { error_message?: string } | undefined)?.error_message;
      setToast({
        type: TOAST_TYPE.ERROR,
        title: t(ROOT_ERRORS[code ?? ""] ?? "page_tree.zil_client.clients_root.error"),
      });
    } finally {
      setIsUpdating(false);
    }
  }, [workspaceSlug, projectId, page, t]);

  return { canManage, isUpdating, toggle };
}
