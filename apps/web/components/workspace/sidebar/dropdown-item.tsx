/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import Link from "next/link";
import { Pin, PinOff } from "lucide-react";
// Base UI directly, not propel's `MenuItem`: the row body is a rich block (logo, role, member count
// and the active row's two action links) and propel's row builds its content from
// `label`/`icon`/`trailing`, which cannot hold it.
import { Menu } from "@base-ui/react/menu";
import { SettingsOutline, TickOutline, UserPlusOutline } from "@makeplane/propel/icons";
import { Button } from "@makeplane/propel/elements/button";
import { WorkspaceAvatar } from "@makeplane/propel/components/workspace-avatar";
// plane imports
import { EUserPermissions } from "@plane/constants";
import { useTranslation } from "@plane/i18n";
import type { IWorkspace } from "@plane/types";
import { cn, getFileURL, getUserRole } from "@plane/utils";
// hooks
import { useFeatureFlag } from "@/hooks/use-feature-flag";

type TProps = {
  workspace: IWorkspace;
  activeWorkspace: IWorkspace | null;
  isPinnedWorkspace: boolean;
  handleItemClick: () => void;
  handleWorkspaceNavigation: (workspace: IWorkspace) => void;
  handleTogglePinnedWorkspace: (workspace: IWorkspace) => void;
  handleClose: () => void;
};
const SidebarDropdownItem = observer(function SidebarDropdownItem(props: TProps) {
  const {
    workspace,
    activeWorkspace,
    isPinnedWorkspace,
    handleItemClick,
    handleWorkspaceNavigation,
    handleTogglePinnedWorkspace,
    handleClose,
  } = props;
  // hooks
  const { t } = useTranslation();
  const isPinnedDefaultWorkspaceEnabled = useFeatureFlag("pinnedDefaultWorkspace");
  // derived values
  const isActiveWorkspace = workspace.id === activeWorkspace?.id;

  return (
    <div
      className={cn("flex w-full flex-col gap-2.5 rounded-md", {
        "bg-layer-transparent-active p-2": isActiveWorkspace,
      })}
    >
      <Menu.Item
        render={<Link href={`/${workspace.slug}`} />}
        id={workspace.id}
        aria-current={isActiveWorkspace ? "page" : undefined}
        onClick={() => {
          handleWorkspaceNavigation(workspace);
          handleItemClick();
        }}
        className={cn("block w-full rounded-md outline-none focus-visible:ring-2 focus-visible:ring-accent-strong", {
          "p-2 hover:bg-layer-transparent-hover data-highlighted:bg-layer-transparent-hover": !isActiveWorkspace,
        })}
      >
        <div className="flex items-center justify-between gap-2 text-body-xs-regular text-primary">
          <div className="relative flex min-w-0 flex-1 items-center justify-start gap-2">
            <WorkspaceAvatar size="lg" src={getFileURL(workspace.logo_url ?? "")} alt={workspace.name} aria-hidden />
            <div className="flex min-w-0 flex-1 flex-col gap-1">
              <div className="truncate text-left text-body-xs-regular leading-5 text-primary">{workspace.name}</div>
              <div className="flex min-w-0 flex-wrap items-center gap-x-1 gap-y-0.5 text-caption-md-regular leading-3.5 text-tertiary capitalize">
                <span className="min-w-0 truncate">{getUserRole(workspace.role)?.toLowerCase() || "guest"}</span>
                <span aria-hidden className="size-1 shrink-0 rounded-full bg-(--text-color-placeholder)" />
                <span className="min-w-0 truncate capitalize">
                  {t("member", { count: workspace.total_members || 0 })}
                </span>
              </div>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-1">
            {isPinnedDefaultWorkspaceEnabled && (
              <button
                type="button"
                onClick={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  handleTogglePinnedWorkspace(workspace);
                }}
                className="flex-shrink-0 rounded-sm p-1 text-tertiary hover:bg-layer-transparent-hover hover:text-secondary"
                title={isPinnedWorkspace ? t("unset_default_workspace") : t("set_default_workspace")}
                aria-label={isPinnedWorkspace ? t("unset_default_workspace") : t("set_default_workspace")}
              >
                {isPinnedWorkspace ? (
                  <PinOff className="h-4 w-4 flex-shrink-0" />
                ) : (
                  <Pin className="h-4 w-4 flex-shrink-0" />
                )}
              </button>
            )}
            {isActiveWorkspace && (
              <span className="shrink-0">
                <TickOutline className="size-4 text-primary" />
              </span>
            )}
          </div>
        </div>
      </Menu.Item>
      {isActiveWorkspace && (
        <div className="flex flex-wrap gap-2">
          {[EUserPermissions.ADMIN, EUserPermissions.MEMBER].includes(workspace?.role) && (
            <Menu.Item
              render={
                <Button
                  variant="secondary"
                  size="sm"
                  stretch="auto"
                  render={<Link href={`/${workspace.slug}/settings`} />}
                />
              }
              onClick={handleClose}
            >
              <SettingsOutline className="size-3.5 shrink-0" />
              {t("settings")}
            </Menu.Item>
          )}
          {[EUserPermissions.ADMIN].includes(workspace?.role) && (
            <Menu.Item
              render={
                <Button
                  variant="secondary"
                  size="sm"
                  stretch="auto"
                  render={<Link href={`/${workspace.slug}/settings/members`} />}
                />
              }
              onClick={handleClose}
            >
              <UserPlusOutline className="size-3.5 shrink-0" />
              {t("project_settings.members.invite_members.title")}
            </Menu.Item>
          )}
        </div>
      )}
    </div>
  );
});

export default SidebarDropdownItem;
