/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { Pin, PinOff, Settings, UserPlus } from "lucide-react";
import { Menu } from "@headlessui/react";
// plane imports
import { EUserPermissions } from "@plane/constants";
import { useTranslation } from "@plane/i18n";
import { CheckIcon } from "@plane/propel/icons";
import type { IWorkspace } from "@plane/types";
import { cn, getFileURL, getUserRole } from "@plane/utils";
// hooks
import { useFeatureFlag } from "@/hooks/use-feature-flag";
// plane web imports
import { SubscriptionPill } from "@/plane-web/components/common/subscription/subscription-pill";

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
  // router
  const { workspaceSlug } = useParams();
  // hooks
  const { t } = useTranslation();
  const isPinnedDefaultWorkspaceEnabled = useFeatureFlag("pinnedDefaultWorkspace");

  return (
    <Link
      key={workspace.id}
      href={`/${workspace.slug}`}
      onClick={() => {
        handleWorkspaceNavigation(workspace);
        handleItemClick();
      }}
      className="w-full"
      id={workspace.id}
    >
      <Menu.Item
        as="div"
        className={cn("px-4 py-2", {
          "bg-layer-transparent-active": workspace.id === activeWorkspace?.id,
          "hover:bg-layer-transparent-hover": workspace.id !== activeWorkspace?.id,
        })}
      >
        <div className="flex items-center justify-between gap-1 rounded-sm p-1 text-13 text-primary">
          <div className="relative flex w-[80%] items-center justify-start gap-2.5">
            <span
              className={`relative flex h-8 w-8 flex-shrink-0 items-center justify-center overflow-hidden rounded-sm border-subtle text-14 font-medium uppercase ${
                !workspace?.logo_url && "bg-[#026292] p-2 text-on-color"
              }`}
            >
              {workspace?.logo_url && workspace.logo_url !== "" ? (
                <img
                  src={getFileURL(workspace.logo_url)}
                  className="absolute top-0 left-0 h-full w-full object-contain"
                  alt={t("workspace_logo")}
                />
              ) : (
                (workspace?.name?.[0] ?? "...")
              )}
            </span>
            <div className="w-[inherit]">
              <div
                className={`truncate text-left text-13 font-medium text-ellipsis ${workspaceSlug === workspace.slug ? "" : "text-secondary"}`}
              >
                {workspace.name}
              </div>
              <div className="flex w-fit gap-2 text-13 text-tertiary capitalize">
                <span>{getUserRole(workspace.role)?.toLowerCase() || "guest"}</span>
                <div className="m-auto h-1 w-1 rounded-full bg-layer-1/50" />
                <span className="capitalize">{t("member", { count: workspace.total_members || 0 })}</span>
              </div>
            </div>
          </div>
          <div className="flex flex-shrink-0 items-center gap-1">
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
            {workspace.id === activeWorkspace?.id ? (
              <span className="flex-shrink-0 p-1">
                <CheckIcon className="h-5 w-5 text-primary" />
              </span>
            ) : (
              <SubscriptionPill workspace={workspace} />
            )}
          </div>
        </div>
        {workspace.id === activeWorkspace?.id && (
          <>
            <div className="mt-2 mb-1 flex gap-2">
              {[EUserPermissions.ADMIN, EUserPermissions.MEMBER].includes(workspace?.role) && (
                <Link
                  href={`/${workspace.slug}/settings`}
                  onClick={(e) => {
                    e.stopPropagation();
                    handleClose();
                  }}
                  className="flex gap-1.5 rounded-md border border-strong bg-layer-2 px-2.5 py-1.5 text-secondary transition-colors hover:border-strong hover:text-secondary hover:shadow-raised-100"
                >
                  <Settings className="my-auto h-4 w-4 flex-shrink-0" />
                  <span className="my-auto text-13 font-medium whitespace-nowrap">{t("settings")}</span>
                </Link>
              )}
              {[EUserPermissions.ADMIN].includes(workspace?.role) && (
                <Link
                  href={`/${workspace.slug}/settings/members`}
                  onClick={(e) => {
                    e.stopPropagation();
                    handleClose();
                  }}
                  className="flex gap-1.5 rounded-md border border-strong bg-layer-2 px-2.5 py-1.5 text-secondary transition-colors hover:border-strong hover:text-secondary hover:shadow-raised-100"
                >
                  <UserPlus className="my-auto h-4 w-4 flex-shrink-0" />
                  <span className="my-auto text-13 font-medium whitespace-nowrap">
                    {t("project_settings.members.invite_members.title")}
                  </span>
                </Link>
              )}
            </div>
          </>
        )}
      </Menu.Item>
    </Link>
  );
});

export default SidebarDropdownItem;
