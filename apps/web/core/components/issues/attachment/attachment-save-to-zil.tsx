/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { MouseEvent } from "react";
import useSWR from "swr";
import { FolderInput } from "lucide-react";
import { useTranslation } from "@plane/i18n";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import { CustomMenu } from "@plane/ui";
// services
import type { TZilErpDocTarget } from "@/services/zil.service";
import { ZilService } from "@/services/zil.service";

const zilService = new ZilService();

type Props = {
  issueId: string;
  attachmentId: string;
  // Targets load on the first menu open: they live in the ERP and most menus are never opened.
  enabled: boolean;
};

/**
 * "Guardar en Zil": copies the attachment into the documents of the Lead / client the work item is
 * linked to in Zil Workspace. Renders nothing unless the work item has such a link.
 */
export function IssueAttachmentSaveToZil({ issueId, attachmentId, enabled }: Props) {
  const { t } = useTranslation();
  const { data } = useSWR(
    enabled ? `ZIL_ISSUE_ERP_DOC_TARGETS_${issueId}` : null,
    () => zilService.getIssueErpDocTargets(issueId),
    { revalidateOnFocus: false, shouldRetryOnError: false }
  );
  const targets = data?.targets ?? [];
  if (targets.length === 0) return null;

  const save = async (e: MouseEvent | undefined, target: TZilErpDocTarget) => {
    // the attachment row itself is a button that opens the file
    e?.stopPropagation();
    try {
      await zilService.saveIssueAttachmentToZil(issueId, attachmentId, target);
      setToast({
        type: TOAST_TYPE.SUCCESS,
        title: t("zil_erp.saved_title"),
        message: t("zil_erp.saved", { name: target.name }),
      });
    } catch {
      setToast({ type: TOAST_TYPE.ERROR, title: t("zil_erp.save_error_title"), message: t("zil_erp.save_error") });
    }
  };

  const label = (
    <div className="flex items-center gap-2">
      <FolderInput className="h-3.5 w-3.5" strokeWidth={2} />
      <span>{t("zil_erp.save_to_zil")}</span>
    </div>
  );

  if (targets.length === 1)
    return <CustomMenu.MenuItem onClick={(e?: MouseEvent) => void save(e, targets[0])}>{label}</CustomMenu.MenuItem>;

  return (
    <CustomMenu.SubMenu trigger={label}>
      {targets.map((target) => (
        <CustomMenu.MenuItem key={`${target.type}-${target.id}`} onClick={(e?: MouseEvent) => void save(e, target)}>
          <span className="flex min-w-0 flex-col">
            <span className="truncate">{target.name}</span>
            <span className="truncate text-caption-sm-regular text-tertiary">
              {t(target.type === "Lead" ? "zil_erp.lead" : "zil_erp.client")}
            </span>
          </span>
        </CustomMenu.MenuItem>
      ))}
    </CustomMenu.SubMenu>
  );
}
