/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useRef } from "react";
import { observer } from "mobx-react";
import { ChevronRight, Folder, FolderOpen } from "lucide-react";
import { useTranslation } from "@plane/i18n";
import { Logo } from "@plane/propel/emoji-icon-picker";
import { PageIcon } from "@plane/propel/icons";
// plane imports
import { cn, getPageName } from "@plane/utils";
// components
import { ListItem } from "@/components/core/list";
import { ZilClientBadge } from "@/components/pages/folder/zil-client-badge";
import { BlockItemAction } from "@/components/pages/list/block-item-action";
// hooks
import { usePlatformOS } from "@/hooks/use-platform-os";
// plane web hooks
import type { EPageStoreType } from "@/hooks/store";
import { usePage } from "@/hooks/store";

const INDENT_PER_LEVEL_PX = 20;

type TPageListBlock = {
  pageId: string;
  storeType: EPageStoreType;
  depth?: number;
  hasChildren?: boolean;
  isExpanded?: boolean;
  isDimmed?: boolean;
  onToggle?: () => void;
};

export const PageListBlock = observer(function PageListBlock(props: TPageListBlock) {
  const { pageId, storeType, depth = 0, hasChildren = false, isExpanded = false, isDimmed = false, onToggle } = props;
  // refs
  const parentRef = useRef(null);
  // hooks
  const page = usePage({
    pageId,
    storeType,
  });
  const { isMobile } = usePlatformOS();
  const { t } = useTranslation();
  // handle page check
  if (!page) return null;
  // derived values
  const { name, logo_props, getRedirectionLink, isFolder, zil_client } = page;
  const FolderIcon = isExpanded ? FolderOpen : Folder;

  return (
    <ListItem
      className={cn({ "opacity-60": isDimmed })}
      leftElementClassName="gap-2"
      prependTitleElement={
        <span className="flex items-center gap-1.5" style={{ paddingLeft: depth * INDENT_PER_LEVEL_PX }}>
          {hasChildren ? (
            <button
              type="button"
              className="grid size-5 place-items-center rounded-sm text-tertiary hover:bg-layer-transparent-hover"
              aria-label={isExpanded ? t("page_tree.collapse") : t("page_tree.expand")}
              aria-expanded={isExpanded}
              disabled={!onToggle}
              onClick={(e) => {
                // the row is a link: don't navigate when toggling
                e.preventDefault();
                e.stopPropagation();
                onToggle?.();
              }}
            >
              <ChevronRight className={cn("size-3.5 transition-transform", { "rotate-90": isExpanded })} />
            </button>
          ) : (
            <span className="size-5" aria-hidden />
          )}
          {logo_props?.in_use ? (
            <Logo logo={logo_props} size={16} type="lucide" />
          ) : isFolder ? (
            <FolderIcon className="h-4 w-4 text-tertiary" />
          ) : (
            <PageIcon className="h-4 w-4 text-tertiary" />
          )}
        </span>
      }
      title={getPageName(name)}
      appendTitleElement={isFolder && zil_client ? <ZilClientBadge client={zil_client} /> : undefined}
      itemLink={getRedirectionLink()}
      actionableItems={<BlockItemAction page={page} parentRef={parentRef} storeType={storeType} />}
      isMobile={isMobile}
      parentRef={parentRef}
    />
  );
});
