/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
// plane imports
import { EUserPermissions, EUserPermissionsLevel } from "@plane/constants";
import { useTranslation } from "@plane/i18n";
// components
import { PageHead } from "@/components/core/page-title";
import { SettingsContentWrapper } from "@/components/settings/content-wrapper";
import { WorkspaceDetails } from "@/components/workspace/settings/workspace-details";
import { ZilClientStatesSettings } from "@/components/workspace/settings/zil-client-states";
// hooks
import { useFeatureFlag } from "@/hooks/use-feature-flag";
import { useWorkspace } from "@/hooks/store/use-workspace";
import { useUserPermissions } from "@/hooks/store/user";
// local imports
import { GeneralWorkspaceSettingsHeader } from "./header";

function GeneralWorkspaceSettingsPage() {
  // store hooks
  const { currentWorkspace } = useWorkspace();
  const { allowPermissions } = useUserPermissions();
  const { t } = useTranslation();
  const isClientStatesEnabled = useFeatureFlag("clientStatesTemplate");
  // derived values
  const isAdmin = allowPermissions([EUserPermissions.ADMIN], EUserPermissionsLevel.WORKSPACE);
  const pageTitle = currentWorkspace?.name
    ? t("workspace_settings.page_label", { workspace: currentWorkspace.name })
    : undefined;

  return (
    <SettingsContentWrapper header={<GeneralWorkspaceSettingsHeader />}>
      <PageHead title={pageTitle} />
      <WorkspaceDetails />
      {isClientStatesEnabled && isAdmin && currentWorkspace?.slug && (
        <ZilClientStatesSettings workspaceSlug={currentWorkspace.slug} />
      )}
    </SettingsContentWrapper>
  );
}

export default observer(GeneralWorkspaceSettingsPage);
