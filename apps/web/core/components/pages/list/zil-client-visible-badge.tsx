/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import { useParams } from "next/navigation";
import { Eye } from "lucide-react";
// plane imports
import { useTranslation } from "@plane/i18n";
// hooks
import type { EPageStoreType } from "@/hooks/store";
import { usePageStore } from "@/hooks/store";
import { useZilProjectPortal } from "@/hooks/use-zil-brands";

type Props = {
  pageId: string;
  storeType: EPageStoreType;
};

/** "Visible al cliente" on a page inside the brand's "Cliente" folder (shown in the client portal). */
export const ZilClientVisibleBadge = observer(function ZilClientVisibleBadge({ pageId, storeType }: Props) {
  const { t } = useTranslation();
  const { workspaceSlug, projectId } = useParams<{ workspaceSlug?: string; projectId?: string }>();
  const { portal } = useZilProjectPortal(workspaceSlug, projectId);
  const { getPageById } = usePageStore(storeType);
  const folderId = portal?.folder_id;
  if (!folderId) return null;

  // walk up the tree: a page anywhere inside the folder is shown
  let parentId = getPageById(pageId)?.parent ?? null;
  for (let depth = 0; parentId && depth < 8; depth++) {
    if (parentId === folderId)
      return (
        <span className="inline-flex flex-shrink-0 items-center gap-1 rounded-sm border border-subtle px-1.5 py-0.5 text-11 text-secondary">
          <Eye className="size-3" />
          {t("zil_brand.visible_to_client")}
        </span>
      );
    parentId = getPageById(parentId)?.parent ?? null;
  }
  return null;
});
