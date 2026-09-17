/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useCallback } from "react";
// plane imports
import { useTranslation } from "@plane/i18n";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import type { TPageKind } from "@plane/types";
// hooks
import type { EPageStoreType } from "@/hooks/store";
import { usePageStore } from "@/hooks/store";
import { useAppRouter } from "@/hooks/use-app-router";
// store
import type { TPageInstance } from "@/store/pages/base-page";
import { MAX_PAGE_TREE_DEPTH } from "@/store/pages/project-page.store";

type Props = {
  page: TPageInstance;
  storeType: EPageStoreType;
};

/**
 * Create sub-pages and folders under a page of the tree.
 */
export const usePageTreeOperations = ({ page, storeType }: Props) => {
  const router = useAppRouter();
  const { t } = useTranslation();
  const { canCurrentUserCreatePage, createPage, getAncestorIds } = usePageStore(storeType);

  const depth = page.id ? getAncestorIds(page.id).length + 1 : 0;
  const canCreateChild =
    !!page.id &&
    canCurrentUserCreatePage &&
    !page.archived_at &&
    page.canCurrentUserEditPage &&
    depth < MAX_PAGE_TREE_DEPTH;

  const createChild = useCallback(
    async (kind: TPageKind) => {
      if (!page.id) return;
      try {
        const newPage = await createPage({
          parent: page.id,
          kind,
          access: page.access,
          ...(kind === "folder" ? { name: t("page_tree.untitled_folder") } : {}),
        });
        // the new page lives in the same project: swap the page id in the parent's link
        if (newPage?.id) router.push(page.getRedirectionLink().replace(/[^/]+$/, newPage.id));
      } catch (error) {
        const message = (error as { error?: string; error_message?: string } | undefined)?.error;
        setToast({
          type: TOAST_TYPE.ERROR,
          title: "Error!",
          message: message || t("page_tree.create_error"),
        });
      }
    },
    [createPage, page, router, t]
  );

  return { canCreateChild, createChild };
};
