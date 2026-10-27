/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { observer } from "mobx-react";
// plane imports
import { EUserPermissions, EUserPermissionsLevel } from "@plane/constants";
import { useTranslation } from "@plane/i18n";
// components
import { NotAuthorizedView } from "@/components/auth-screens/not-authorized-view";
import { PageHead } from "@/components/core/page-title";
import { SettingsContentWrapper } from "@/components/settings/content-wrapper";
import { SettingsHeading } from "@/components/settings/heading";
import { TrashList } from "@/components/trash";
// hooks
import { useProject } from "@/hooks/store/use-project";
import { useUserPermissions } from "@/hooks/store/user";
import { useFeatureFlag } from "@/hooks/use-feature-flag";
// services
import type { TTrashItemType } from "@/services/trash.service";
// local imports
import type { Route } from "./+types/page";
import { TrashProjectSettingsHeader } from "./header";

function TrashSettingsPage({ params }: Route.ComponentProps) {
  const { workspaceSlug, projectId } = params;
  // states
  const [activeType, setActiveType] = useState<TTrashItemType>("issue");
  // store hooks
  const { workspaceUserInfo, allowPermissions } = useUserPermissions();
  const { currentProjectDetails } = useProject();
  // feature flag
  const isTrashEnabled = useFeatureFlag("trashRestore");
  // translation
  const { t } = useTranslation();
  // derived values
  const pageTitle = currentProjectDetails?.name
    ? `${currentProjectDetails?.name} settings - ${t("project_settings.trash.label")}`
    : undefined;
  const canPerformProjectAdminActions = allowPermissions([EUserPermissions.ADMIN], EUserPermissionsLevel.PROJECT);
  const isWorkspaceAdmin = allowPermissions([EUserPermissions.ADMIN], EUserPermissionsLevel.WORKSPACE);
  const tabs: { type: TTrashItemType; label: string }[] = [
    { type: "issue", label: t("project_settings.trash.tab_issue") },
    { type: "page", label: t("project_settings.trash.tab_page") },
    { type: "cycle", label: t("project_settings.trash.tab_cycle") },
    { type: "module", label: t("project_settings.trash.tab_module") },
    ...(isWorkspaceAdmin ? [{ type: "project" as const, label: t("project_settings.trash.tab_project") }] : []),
  ];

  if (!isTrashEnabled) return null;

  if (workspaceUserInfo && !canPerformProjectAdminActions) {
    return <NotAuthorizedView section="settings" isProjectView className="h-auto" />;
  }

  return (
    <SettingsContentWrapper header={<TrashProjectSettingsHeader />}>
      <PageHead title={pageTitle} />
      <section className="w-full">
        <SettingsHeading
          title={t("project_settings.trash.title")}
          description={t("project_settings.trash.description")}
        />
        <div className="mt-6 flex gap-2 border-b border-subtle">
          {tabs.map((tab) => (
            <button
              key={tab.type}
              type="button"
              onClick={() => setActiveType(tab.type)}
              className={`px-3 py-2 text-body-sm-medium ${
                activeType === tab.type ? "border-b-2 border-accent-strong text-primary" : "text-tertiary"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
        <div className="mt-6">
          <TrashList workspaceSlug={workspaceSlug} projectId={projectId} type={activeType} />
        </div>
      </section>
    </SettingsContentWrapper>
  );
}

export default observer(TrashSettingsPage);
