/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { observer } from "mobx-react";
import { Building2, FilePlus2, FolderOpen, FolderPlus } from "lucide-react";
// plane imports
import { EPageAccess } from "@plane/constants";
import { useTranslation } from "@plane/i18n";
import { Button } from "@plane/propel/button";
import { Logo } from "@plane/propel/emoji-icon-picker";
import type { TPageNavigationTabs } from "@plane/types";
import { getPageName } from "@plane/utils";
// components
import { ListLayout } from "@/components/core/list";
import { PageTreeNode } from "@/components/pages/list/tree-node";
// hooks
import type { EPageStoreType } from "@/hooks/store";
import { usePageStore } from "@/hooks/store";
import { usePageTreeOperations } from "@/hooks/use-page-tree-operations";
// store
import type { TPageInstance } from "@/store/pages/base-page";
// local imports
import { ZilClientBadge } from "./zil-client-badge";
import { ZilClientPickerModal } from "./zil-client-picker-modal";

type Props = {
  page: TPageInstance;
  storeType: EPageStoreType;
};

const getTabForPage = (page: TPageInstance): TPageNavigationTabs => {
  if (page.archived_at) return "archived";
  return page.access === EPageAccess.PRIVATE ? "private" : "public";
};

/**
 * A folder has no editor: it shows its name, the linked Zil client and an index of its children.
 */
export const FolderPageView = observer(function FolderPageView(props: Props) {
  const { page, storeType } = props;
  // states
  const [isZilClientModalOpen, setIsZilClientModalOpen] = useState(false);
  // hooks
  const { t } = useTranslation();
  const { data } = usePageStore(storeType);
  const { canCreateChild, createChild } = usePageTreeOperations({ page, storeType });
  // derived values
  const { name, logo_props, zil_client, canCurrentUserEditPage, archived_at, updateTitle } = page;
  const canEdit = canCurrentUserEditPage && !archived_at;
  // children are shown regardless of their access, each in the tab it belongs to
  const children = Object.values(data).filter(
    (child) => child.parent === page.id && (!!archived_at || !child.archived_at)
  );
  const orderedChildren = [
    ...children.filter((child) => child.isFolder),
    ...children.filter((child) => !child.isFolder),
  ];

  return (
    <div className="flex size-full flex-col overflow-y-auto">
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-4 px-page-x py-8">
        <div className="flex items-center gap-3">
          <span className="grid size-10 flex-shrink-0 place-items-center rounded-md bg-layer-3">
            {logo_props?.in_use ? (
              <Logo logo={logo_props} size={22} type="lucide" />
            ) : (
              <FolderOpen className="size-5 text-tertiary" />
            )}
          </span>
          <input
            className="w-full min-w-0 bg-transparent text-20 font-semibold text-primary outline-none placeholder:text-placeholder disabled:cursor-default"
            value={name ?? ""}
            placeholder={getPageName(undefined)}
            disabled={!canEdit}
            onChange={(e) => updateTitle(e.target.value)}
          />
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {zil_client && <ZilClientBadge client={zil_client} />}
          {canEdit && (
            <Button variant="ghost" size="lg" onClick={() => setIsZilClientModalOpen(true)}>
              <Building2 className="size-3.5" />
              {zil_client ? t("page_tree.zil_client.change") : t("page_tree.zil_client.link")}
            </Button>
          )}
          <span className="text-13 text-tertiary">
            {t("page_tree.folder.items_count", { count: orderedChildren.length })}
          </span>
          {canCreateChild && (
            <div className="ml-auto flex items-center gap-2">
              <Button variant="secondary" size="lg" onClick={() => createChild("folder")}>
                <FolderPlus className="size-3.5" />
                {t("page_tree.new_folder")}
              </Button>
              <Button variant="primary" size="lg" onClick={() => createChild("page")}>
                <FilePlus2 className="size-3.5" />
                {t("page_tree.new_page")}
              </Button>
            </div>
          )}
        </div>

        {orderedChildren.length > 0 ? (
          <div className="rounded-md border border-subtle">
            <ListLayout>
              {orderedChildren.map((child) => (
                <PageTreeNode
                  key={child.id}
                  pageId={child.id as string}
                  pageType={getTabForPage(child)}
                  storeType={storeType}
                  depth={0}
                />
              ))}
            </ListLayout>
          </div>
        ) : (
          <div className="flex flex-col items-center gap-1 rounded-md border border-dashed border-subtle py-16 text-center">
            <FolderOpen className="mb-2 size-8 text-placeholder" />
            <h4 className="text-14 font-medium text-primary">{t("page_tree.folder.empty_title")}</h4>
            <p className="text-13 text-secondary">{t("page_tree.folder.empty_description")}</p>
          </div>
        )}
      </div>
      <ZilClientPickerModal isOpen={isZilClientModalOpen} onClose={() => setIsZilClientModalOpen(false)} page={page} />
    </div>
  );
});
