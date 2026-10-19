/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import { useParams } from "next/navigation";
// plane imports
import { useTranslation } from "@plane/i18n";
// components
import { PageHead } from "@/components/core/page-title";
import { ZilBrandSheet } from "@/components/zil-brand/brand-sheet";
// hooks
import { useProject } from "@/hooks/store/use-project";

function ProjectBrandPage() {
  const { workspaceSlug, projectId } = useParams();
  const { t } = useTranslation();
  const { getProjectById } = useProject();
  const project = projectId ? getProjectById(projectId.toString()) : undefined;
  const title = project?.name ? `${project.name} - ${t("sidebar.brand")}` : undefined;

  if (!workspaceSlug || !projectId) return null;
  return (
    <>
      <PageHead title={title} />
      <div className="relative h-full w-full overflow-hidden overflow-y-auto">
        <ZilBrandSheet workspaceSlug={workspaceSlug.toString()} projectId={projectId.toString()} />
      </div>
    </>
  );
}

export default observer(ProjectBrandPage);
