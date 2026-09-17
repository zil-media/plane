/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
// plane imports
import type { TPageNavigationTabs } from "@plane/types";
// hooks
import type { EPageStoreType } from "@/hooks/store";
import { usePageStore } from "@/hooks/store";
// local imports
import { PageListBlock } from "./block";

type TPageTreeNode = {
  pageId: string;
  pageType: TPageNavigationTabs;
  storeType: EPageStoreType;
  depth: number;
};

export const PageTreeNode = observer(function PageTreeNode(props: TPageTreeNode) {
  const { pageId, pageType, storeType, depth } = props;
  // store hooks
  const { getTreeChildIds, hasActiveSearchOrFilters, isPageExpanded, isPageMatchingSearch, toggleExpanded } =
    usePageStore(storeType);
  // derived values
  const childIds = getTreeChildIds(pageId, pageType);
  const hasChildren = childIds.length > 0;
  // while searching, ancestors of matches are forced open without touching the saved state
  const isExpanded = hasChildren && (hasActiveSearchOrFilters || isPageExpanded(pageId));
  const isDimmed = hasActiveSearchOrFilters && !isPageMatchingSearch(pageId);

  return (
    <>
      <PageListBlock
        pageId={pageId}
        storeType={storeType}
        depth={depth}
        hasChildren={hasChildren}
        isExpanded={isExpanded}
        isDimmed={isDimmed}
        onToggle={hasActiveSearchOrFilters ? undefined : () => toggleExpanded(pageId)}
      />
      {isExpanded &&
        childIds.map((childId) => (
          <PageTreeNode key={childId} pageId={childId} pageType={pageType} storeType={storeType} depth={depth + 1} />
        ))}
    </>
  );
});
