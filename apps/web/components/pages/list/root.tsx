/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
// types
import type { TPageNavigationTabs } from "@plane/types";
// components
import { ListLayout } from "@/components/core/list";
// plane web hooks
import type { EPageStoreType } from "@/hooks/store";
import { usePageStore } from "@/hooks/store";
// local imports
import { PageTreeNode } from "./tree-node";

type TPagesListRoot = {
  pageType: TPageNavigationTabs;
  storeType: EPageStoreType;
};

export const PagesListRoot = observer(function PagesListRoot(props: TPagesListRoot) {
  const { pageType, storeType } = props;
  // store hooks
  const { getCurrentProjectFilteredPageIdsByTab, getTreeChildIds } = usePageStore(storeType);
  // derived values
  const filteredPageIds = getCurrentProjectFilteredPageIdsByTab(pageType);
  const rootPageIds = getTreeChildIds(null, pageType);

  if (!filteredPageIds) return <></>;
  return (
    <ListLayout>
      {rootPageIds.map((pageId) => (
        <PageTreeNode key={pageId} pageId={pageId} pageType={pageType} storeType={storeType} depth={0} />
      ))}
    </ListLayout>
  );
});
