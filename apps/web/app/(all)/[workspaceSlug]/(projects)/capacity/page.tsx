/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import { useTranslation } from "@plane/i18n";
// components
import { PageHead } from "@/components/core/page-title";
import { WorkspaceCapacityRoot } from "@/components/workspace/capacity";
// hooks
import { useWorkspace } from "@/hooks/store/use-workspace";

function WorkspaceCapacityPage() {
  const { t } = useTranslation();
  const { currentWorkspace } = useWorkspace();
  // derived values
  const pageTitle = currentWorkspace?.name
    ? t("workspace_capacity.page_label", { workspace: currentWorkspace.name })
    : undefined;

  return (
    <>
      <PageHead title={pageTitle} />
      <WorkspaceCapacityRoot />
    </>
  );
}

export default observer(WorkspaceCapacityPage);
