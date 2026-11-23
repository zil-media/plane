/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// components
import { observer } from "mobx-react";
import { useParams, usePathname, useRouter } from "next/navigation";
import Link from "next/link";
import { ExternalLink } from "lucide-react";
import { useTranslation } from "@plane/i18n";
import { cn } from "@plane/utils";
import { TopNavPowerK } from "@/components/navigation";
import { HelpMenuRoot } from "@/components/workspace/sidebar/help-section/root";
import { UserMenuRoot } from "@/components/workspace/sidebar/user-menu-root";
import { WorkspaceMenuRoot } from "@/components/workspace/sidebar/workspace-menu-root";
import { useAppRailPreferences } from "@/hooks/use-navigation-preferences";
import { Tooltip } from "@makeplane/propel/components/tooltip";
import { IconButton } from "@makeplane/propel/elements/icon-button";
import { InboxOutline } from "@makeplane/propel/icons";
import useSWR from "swr";
import { useWorkspaceNotifications } from "@/hooks/store/notifications";
import { getZilWorkspaceUrl } from "@/helpers/zil-workspace";

export const TopNavigationRoot = observer(function TopNavigationRoot() {
  const { t } = useTranslation();
  // router
  const { workspaceSlug } = useParams();
  const pathname = usePathname();
  const router = useRouter();

  // Navigate to the Ops workspace home ("Inicio"). Guarded: only push when a
  // workspaceSlug is present so we never route to "/undefined/".
  const handleGoHome = () => {
    if (workspaceSlug) router.push(`/${workspaceSlug.toString()}/`);
  };

  // store hooks
  const { unreadNotificationsCount, getUnreadNotificationsCount } = useWorkspaceNotifications();
  const { preferences } = useAppRailPreferences();

  const showLabel = preferences.displayMode === "icon_with_label";

  // Fetch notification count
  useSWR(
    workspaceSlug ? "WORKSPACE_UNREAD_NOTIFICATION_COUNT" : null,
    workspaceSlug ? () => getUnreadNotificationsCount(workspaceSlug.toString()) : null
  );

  // Calculate notification count
  const isMentionsEnabled = unreadNotificationsCount.mention_unread_notifications_count > 0;
  const totalNotifications = isMentionsEnabled
    ? unreadNotificationsCount.mention_unread_notifications_count
    : unreadNotificationsCount.total_unread_notifications_count;

  return (
    <div
      className={cn(
        "desktop-header z-27 flex min-h-10 w-full items-center gap-2 bg-canvas px-3.5 transition-all duration-300 md:gap-0",
        {
          "px-2": !showLabel,
        }
      )}
    >
      <div className="flex shrink-0 items-center gap-1.5 md:flex-1">
        {/* Brand lockup — a single dark navy chip holding the animated Zil mark
            + the "Ops" wordmark, clickable → navigates to the Ops workspace
            home. The navy backdrop gives the celeste/blanco + Sol de Mayo good
            contrast on the light nav; fixed dark color stays dark in both themes
            (like the letter-avatar's fixed bg). Animation plays inside via
            overflow-hidden. The workspace switcher stays OUTSIDE the click area. */}
        <button
          type="button"
          onClick={handleGoHome}
          aria-label="Ir al inicio de Ops"
          className="focus-visible:ring-primary/40 flex h-8 shrink-0 cursor-pointer items-center gap-1.5 rounded-md transition-opacity hover:opacity-80 focus:outline-none focus-visible:ring-2"
        >
          <svg
            viewBox="0 0 57 32"
            className="h-4 w-auto shrink-0 text-secondary"
            fill="currentColor"
            xmlns="http://www.w3.org/2000/svg"
            aria-hidden="true"
          >
            <path d="M12.8857 19.0928H21.4629V32H0L10.1328 19.0928H1.67871V6.18555H23.0186L12.8857 19.0928ZM39.0742 32H26.166V6.18555H39.0742V32ZM57.001 32H44.0938V0H57.001V32Z" />
          </svg>
          <span className="truncate text-14 font-medium text-secondary">Ops</span>
        </button>
        <div className="mx-1 h-5 w-px shrink-0 border-l border-subtle" />
        {/* Workspace Menu */}
        <div className="shrink-0">
          <WorkspaceMenuRoot variant="top-navigation" />
        </div>
      </div>
      {/* Power K Search */}
      <div className="desktop-header-actions min-w-0 flex-1 md:flex-none">
        <TopNavPowerK />
      </div>
      {/* Additional Actions */}
      <div className="desktop-header-actions flex shrink-0 items-center justify-end gap-1 md:flex-1">
        <Tooltip label={t("sidebar.inbox")} side="bottom">
          <IconButton
            variant="ghost"
            size="md"
            aria-label={t("sidebar.inbox")}
            aria-current={pathname?.includes("/notifications/") ? "page" : undefined}
            render={
              <Link
                href={`/${workspaceSlug?.toString()}/notifications/`}
                className={
                  pathname?.includes("/notifications/") ? "bg-layer-transparent-selected !text-icon-primary" : undefined
                }
              />
            }
          >
            <span className="relative flex">
              <InboxOutline className="size-4.5" />
              {totalNotifications > 0 && (
                <span className="absolute top-0 right-0 size-2 rounded-full bg-danger-primary" />
              )}
            </span>
          </IconButton>
        </Tooltip>
        <HelpMenuRoot />
        <UserMenuRoot />
        {/* Open Zil Workspace — placed right of the profile avatar. System secondary-button style. */}
        <a
          href={getZilWorkspaceUrl()}
          aria-label="Abrir Zil Workspace"
          className="inline-flex h-6 items-center gap-1 rounded-md border border-strong bg-layer-2 px-2 text-body-xs-medium text-secondary shadow-raised-100 transition-colors hover:bg-layer-2-hover"
        >
          <ExternalLink className="size-3.5" />
          Workspace
        </a>
      </div>
    </div>
  );
});
