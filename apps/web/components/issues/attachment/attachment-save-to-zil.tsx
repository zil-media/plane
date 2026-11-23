/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import useSWR from "swr";
import { FolderInput } from "lucide-react";
import { useTranslation } from "@plane/i18n";
import { setToast } from "@plane/blocks/toast";
import { MenuItem, MenuSubmenu, MenuSubmenuContent, MenuSubmenuTrigger } from "@makeplane/propel/components/menu";
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

  const save = async (target: TZilErpDocTarget) => {
    try {
      await zilService.saveIssueAttachmentToZil(issueId, attachmentId, target);
      setToast({
        type: "success",
        title: t("zil_erp.saved_title"),
        message: t("zil_erp.saved", { name: target.name }),
      });
    } catch {
      setToast({ type: "error", title: t("zil_erp.save_error_title"), message: t("zil_erp.save_error") });
    }
  };

  const icon = <FolderInput className="size-3.5" strokeWidth={2} />;

  if (targets.length === 1)
    return <MenuItem icon={icon} label={t("zil_erp.save_to_zil")} onClick={() => void save(targets[0])} />;

  return (
    <MenuSubmenu>
      <MenuSubmenuTrigger label={t("zil_erp.save_to_zil")} />
      <MenuSubmenuContent>
        {targets.map((target) => (
          <MenuItem
            key={`${target.type}-${target.id}`}
            label={`${target.name} (${t(target.type === "Lead" ? "zil_erp.lead" : "zil_erp.client")})`}
            onClick={() => void save(target)}
          />
        ))}
      </MenuSubmenuContent>
    </MenuSubmenu>
  );
}
