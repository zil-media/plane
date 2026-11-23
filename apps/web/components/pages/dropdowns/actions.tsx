/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { isValidElement, useMemo, useState } from "react";
import { observer } from "mobx-react";
import { useParams } from "next/navigation";
import { Building2, FilePlus2, FolderPlus } from "lucide-react";
import {
  ArchiveOutline,
  CopyOutline,
  DeleteOutline,
  ExportOutline,
  GlobeOutline,
  LinkOutline,
  LockOutline,
  LockedOutline,
  MoreHorizontalOutline,
  NewTabOutline,
  RestoreOutline,
  UnlockedOutline,
} from "@makeplane/propel/icons";
// constants
import { EPageAccess } from "@plane/constants";
// plane ui
import { useTranslation } from "@plane/i18n";
import { Icon } from "@makeplane/propel/components/icon";
import { IconButton } from "@makeplane/propel/components/icon-button";
import { Menu, MenuContent, MenuItem, MenuTrigger } from "@makeplane/propel/components/menu";
import type { TContextMenuItem } from "@plane/blocks/context-menu";
import { ContextMenu, getRenderableItems, resolveItemVariant } from "@plane/blocks/context-menu";
// components
import { ZilClientPickerModal } from "@/components/pages/folder/zil-client-picker-modal";
import { DeletePageModal } from "@/components/pages/modals/delete-page-modal";
import { usePageTreeOperations } from "@/hooks/use-page-tree-operations";
// hooks
import { usePageOperations } from "@/hooks/use-page-operations";
// plane web components
import { MovePageModal } from "@/components/pages/modals/move-page-modal";
// plane web hooks
import type { EPageStoreType } from "@/hooks/store";
import { usePageFlag } from "@/hooks/use-page-flag";
// store types
import type { TPageInstance } from "@/store/pages/base-page";

export type TPageActions =
  | "full-screen"
  | "sticky-toolbar"
  | "copy-markdown"
  | "toggle-lock"
  | "toggle-access"
  | "open-in-new-tab"
  | "copy-link"
  | "make-a-copy"
  | "archive-restore"
  | "delete"
  | "version-history"
  | "export"
  | "move"
  | "add-sub-page"
  | "add-folder"
  | "link-zil-client";

type Props = {
  extraOptions?: (TContextMenuItem & { key: TPageActions })[];
  optionsOrder: TPageActions[];
  page: TPageInstance;
  parentRef?: React.RefObject<HTMLElement | null>;
  storeType: EPageStoreType;
};

export const PageActions = observer(function PageActions(props: Props) {
  const { extraOptions, optionsOrder, page, parentRef, storeType } = props;
  // plane hooks
  const { t } = useTranslation();
  // states
  const [deletePageModal, setDeletePageModal] = useState(false);
  const [movePageModal, setMovePageModal] = useState(false);
  const [zilClientModal, setZilClientModal] = useState(false);
  // params
  const { workspaceSlug } = useParams();
  // page flag
  const { isMovePageEnabled } = usePageFlag({
    workspaceSlug: workspaceSlug?.toString() ?? "",
  });
  // page operations
  const { pageOperations } = usePageOperations({
    page,
  });
  const { canCreateChild, createChild } = usePageTreeOperations({ page, storeType });
  // derived values
  const {
    access,
    archived_at,
    is_locked,
    canCurrentUserArchivePage,
    zilArchiveLock,
    canCurrentUserChangeAccess,
    canCurrentUserDeletePage,
    canCurrentUserDuplicatePage,
    canCurrentUserLockPage,
    canCurrentUserMovePage,
    canCurrentUserEditPage,
    isFolder,
    zil_client,
  } = page;
  // menu items
  const MENU_ITEMS = useMemo(
    function MENU_ITEMS() {
      const menuItems: (TContextMenuItem & { key: TPageActions })[] = [
        {
          key: "toggle-lock",
          action: () => {
            pageOperations.toggleLock();
          },
          title: is_locked ? "Unlock" : "Lock",
          icon: is_locked ? UnlockedOutline : LockedOutline,
          shouldRender: canCurrentUserLockPage,
        },
        {
          key: "toggle-access",
          action: () => {
            pageOperations.toggleAccess();
          },
          title: access === EPageAccess.PUBLIC ? "Make private" : "Make public",
          icon: access === EPageAccess.PUBLIC ? LockOutline : GlobeOutline,
          shouldRender: canCurrentUserChangeAccess && !archived_at,
        },
        {
          key: "open-in-new-tab",
          action: pageOperations.openInNewTab,
          title: "Open in new tab",
          icon: NewTabOutline,
          shouldRender: true,
        },
        {
          key: "copy-link",
          action: pageOperations.copyLink,
          title: "Copy link",
          icon: LinkOutline,
          shouldRender: true,
        },
        {
          key: "make-a-copy",
          action: () => {
            pageOperations.duplicate();
          },
          title: "Make a copy",
          icon: CopyOutline,
          shouldRender: canCurrentUserDuplicatePage,
        },
        {
          key: "archive-restore",
          action: () => {
            pageOperations.toggleArchive();
          },
          title: archived_at ? "Restore" : "Archive",
          icon: archived_at ? RestoreOutline : ArchiveOutline,
          // archiving the clients folder archives every client folder in it, and the next sync makes a new one
          // (and brings the client folders back into it): the action only multiplies folders
          shouldRender: (canCurrentUserArchivePage || !!zilArchiveLock) && (!!archived_at || !page.is_zil_clients_root),
          // a client's folder made by the sync is archived and restored by it: shown, but explained instead
          disabled: !!zilArchiveLock,
          description:
            zilArchiveLock === "client_active"
              ? t("page_tree.zil_client.auto.archive_locked")
              : zilArchiveLock === "client_left"
                ? t("page_tree.zil_client.auto.restore_locked")
                : undefined,
        },
        {
          key: "delete",
          action: () => {
            setDeletePageModal(true);
          },
          title: "Delete",
          icon: DeleteOutline,
          shouldRender: canCurrentUserDeletePage && !!archived_at,
        },
        {
          key: "move",
          action: () => setMovePageModal(true),
          title: t("page_tree.move.action"),
          icon: ExportOutline,
          shouldRender: canCurrentUserMovePage && isMovePageEnabled,
        },
        {
          key: "add-sub-page",
          action: () => createChild("page"),
          title: t("page_tree.add_sub_page"),
          icon: FilePlus2,
          shouldRender: canCreateChild,
        },
        {
          key: "add-folder",
          action: () => createChild("folder"),
          title: t("page_tree.add_folder"),
          icon: FolderPlus,
          shouldRender: canCreateChild,
        },
        {
          key: "link-zil-client",
          action: () => setZilClientModal(true),
          title: zil_client ? t("page_tree.zil_client.change") : t("page_tree.zil_client.link"),
          icon: Building2,
          shouldRender: isFolder && canCurrentUserEditPage && !archived_at && !page.is_zil_clients_root,
          // unlinked or linked to another client, the folder the sync made would get a twin on its next run
          disabled: !!zil_client?.auto_created,
          description: zil_client?.auto_created ? t("page_tree.zil_client.auto.link_locked") : undefined,
        },
      ];
      if (extraOptions) {
        menuItems.push(...extraOptions);
      }
      return menuItems;
    },
    [
      extraOptions,
      is_locked,
      canCurrentUserLockPage,
      access,
      canCurrentUserChangeAccess,
      archived_at,
      canCurrentUserDuplicatePage,
      canCurrentUserArchivePage,
      zilArchiveLock,
      canCurrentUserDeletePage,
      canCurrentUserMovePage,
      isMovePageEnabled,
      pageOperations,
      canCreateChild,
      createChild,
      canCurrentUserEditPage,
      isFolder,
      zil_client,
      page.is_zil_clients_root,
      t,
    ]
  );
  // arrange options
  const arrangedOptions = useMemo<(TContextMenuItem & { key: TPageActions })[]>(
    () =>
      optionsOrder
        .map((key) => MENU_ITEMS.find((item) => item.key === key))
        .filter((item): item is TContextMenuItem & { key: TPageActions } => !!item),
    [optionsOrder, MENU_ITEMS]
  );

  return (
    <>
      <MovePageModal isOpen={movePageModal} onClose={() => setMovePageModal(false)} page={page} />
      {isFolder && (
        <ZilClientPickerModal isOpen={zilClientModal} onClose={() => setZilClientModal(false)} page={page} />
      )}
      <DeletePageModal
        isOpen={deletePageModal}
        onClose={() => setDeletePageModal(false)}
        page={page}
        storeType={storeType}
      />
      {parentRef && <ContextMenu parentRef={parentRef} items={arrangedOptions} />}
      <Menu>
        <MenuTrigger
          render={
            <IconButton
              variant="ghost"
              size="sm"
              aria-label={t("aria_labels.common.more_actions")}
              icon={<Icon icon={MoreHorizontalOutline} />}
              // the list row is a link: keep the trigger from navigating or bubbling to it
              onClick={(e) => {
                e.preventDefault();
                e.stopPropagation();
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") e.stopPropagation();
              }}
            />
          }
        />
        <MenuContent side="bottom" align="end">
          {getRenderableItems(arrangedOptions).map((item) => (
            <MenuItem
              key={item.key}
              variant={resolveItemVariant(item)}
              label={item.title ?? ""}
              description={item.description}
              icon={item.icon && <Icon icon={item.icon} />}
              // `customContent` (the full-width / sticky-toolbar switches) sits at the row's inline end.
              trailing={isValidElement(item.customContent) ? item.customContent : undefined}
              disabled={item.disabled}
              closeOnClick={item.closeOnClick}
              onClick={(e) => {
                e.stopPropagation();
                item.action?.();
              }}
            />
          ))}
        </MenuContent>
      </Menu>
    </>
  );
});
