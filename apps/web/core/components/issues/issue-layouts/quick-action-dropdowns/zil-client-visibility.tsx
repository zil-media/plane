/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { Eye, EyeOff } from "lucide-react";
// plane imports
import { useTranslation } from "@plane/i18n";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import type { TIssue } from "@plane/types";
import type { TContextMenuItem } from "@plane/ui";
// hooks
import { useIssueDetail } from "@/hooks/store/use-issue-detail";
import { useLabel } from "@/hooks/store/use-label";

// the label a brand project's client portal shows (seeded by Ops, see plane.utils.zil_client_portal)
const VISIBLE_LABEL = "visible al cliente";

/**
 * "Mostrar al cliente" / "Ocultar al cliente": puts or takes off the label that shows a work item in
 * the brand's client portal. Only where that label exists (a brand project).
 */
export const useZilClientVisibilityMenuItem = (
  issue: TIssue,
  workspaceSlug: string | undefined,
  isEditingAllowed: boolean
): TContextMenuItem => {
  const { t } = useTranslation();
  const { getProjectLabels } = useLabel();
  const { updateIssue } = useIssueDetail();
  const label = getProjectLabels(issue?.project_id)?.find((item) => item.name.trim().toLowerCase() === VISIBLE_LABEL);
  const labelIds = issue?.label_ids ?? [];
  const visible = !!label && labelIds.includes(label.id);

  const toggle = async () => {
    if (!label || !workspaceSlug || !issue.project_id) return;
    const next = visible ? labelIds.filter((id) => id !== label.id) : [...labelIds, label.id];
    try {
      await updateIssue(workspaceSlug, issue.project_id, issue.id, { label_ids: next });
    } catch {
      setToast({ type: TOAST_TYPE.ERROR, title: t("toast.error"), message: t("zil_brand.portal_error") });
    }
  };

  return {
    key: "zil-client-visibility",
    title: visible ? t("zil_brand.hide_from_client") : t("zil_brand.show_to_client"),
    icon: visible ? EyeOff : Eye,
    action: () => void toggle(),
    shouldRender: !!label && isEditingAllowed,
  };
};
