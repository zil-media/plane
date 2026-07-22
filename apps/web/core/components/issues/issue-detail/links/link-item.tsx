/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { observer } from "mobx-react";
import { RefreshCw } from "lucide-react";

import { useTranslation } from "@plane/i18n";
import { LinkIcon, CopyIcon, EditIcon, TrashIcon } from "@plane/propel/icons";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import { Tooltip } from "@plane/propel/tooltip";
import type { TIssueLinkProvider, TIssueServiceType } from "@plane/types";
import { EIssueServiceType } from "@plane/types";
// ui
import { CustomMenu } from "@plane/ui";
import { calculateTimeAgo, cn, copyTextToClipboard } from "@plane/utils";
// helpers
// hooks
import { useIssueDetail } from "@/hooks/store/use-issue-detail";
import { usePlatformOS } from "@/hooks/use-platform-os";
import type { TLinkOperationsModal } from "./create-update-link-modal";

type TIssueLinkItem = {
  workspaceSlug?: string;
  projectId?: string;
  linkId: string;
  linkOperations: TLinkOperationsModal;
  isNotAllowed: boolean;
  issueServiceType?: TIssueServiceType;
};

// Minimal provider glyphs for the rich-card badge/placeholder. Kept as tiny
// inline SVGs so no new asset/icon-package dependency is needed.
function FigmaGlyph({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} xmlns="http://www.w3.org/2000/svg">
      <path d="M8 24c2.21 0 4-1.79 4-4v-4H8c-2.21 0-4 1.79-4 4s1.79 4 4 4z" fill="#0ACF83" />
      <path d="M4 12c0-2.21 1.79-4 4-4h4v8H8c-2.21 0-4-1.79-4-4z" fill="#A259FF" />
      <path d="M4 4c0-2.21 1.79-4 4-4h4v8H8C5.79 8 4 6.21 4 4z" fill="#F24E1E" />
      <path d="M12 0h4c2.21 0 4 1.79 4 4s-1.79 4-4 4h-4V0z" fill="#FF7262" />
      <path d="M20 12c0 2.21-1.79 4-4 4s-4-1.79-4-4 1.79-4 4-4 4 1.79 4 4z" fill="#1ABCFE" />
    </svg>
  );
}

function GoogleDriveGlyph({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} xmlns="http://www.w3.org/2000/svg">
      <path d="M7.71 3.5 1.15 15l3.43 6h6.86l-3.43-6 3.43-6L7.71 3.5z" fill="#0066DA" />
      <path d="M16.29 3.5H7.71l3.43 6h8.6L16.29 3.5z" fill="#00AC47" />
      <path d="M19.75 9.5h-8.6l3.43 6h6.86l1.74-3-3.43-3z" fill="#EA4335" />
      <path d="M4.58 21h14.84l3.43-6H8.01l-3.43 6z" fill="#FFBA00" />
    </svg>
  );
}

const PROVIDER_GLYPHS: Record<TIssueLinkProvider, (props: { className?: string }) => JSX.Element> = {
  figma: FigmaGlyph,
  google_drive: GoogleDriveGlyph,
};

export const IssueLinkItem = observer(function IssueLinkItem(props: TIssueLinkItem) {
  // props
  const {
    workspaceSlug,
    projectId,
    linkId,
    linkOperations,
    isNotAllowed,
    issueServiceType = EIssueServiceType.ISSUES,
  } = props;
  // hooks
  const {
    toggleIssueLinkModal: toggleIssueLinkModalStore,
    setIssueLinkData,
    fetchLinks,
    link: { getLinkById },
  } = useIssueDetail(issueServiceType);
  const { isMobile } = usePlatformOS();
  const { t } = useTranslation();
  // state
  const [isRefreshing, setIsRefreshing] = useState(false);

  const linkDetail = getLinkById(linkId);
  if (!linkDetail) return <></>;

  // const Icon = getIconForLink(linkDetail.url);
  const faviconUrl: string | undefined | null = linkDetail.metadata?.favicon;
  const linkTitle: string | undefined | null = linkDetail.metadata?.title;
  const provider = linkDetail.metadata?.provider;
  const ProviderGlyph = provider ? PROVIDER_GLYPHS[provider] : undefined;
  const displayTitle = linkDetail.title && linkDetail.title !== "" ? linkDetail.title : linkDetail.url;

  const toggleIssueLinkModal = (modalToggle: boolean) => {
    toggleIssueLinkModalStore(modalToggle);
    setIssueLinkData(linkDetail);
  };

  const handleCopyLink = () => {
    copyTextToClipboard(linkDetail.url);
    setToast({
      type: TOAST_TYPE.SUCCESS,
      title: t("common.link_copied"),
      message: t("common.link_copied_to_clipboard"),
    });
  };

  const handleRefresh = async (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (isRefreshing || isNotAllowed) return;
    setIsRefreshing(true);
    try {
      // Re-submitting the same url re-dispatches the backend crawl task,
      // which re-fetches provider metadata (thumbnail, crawl timestamp).
      await linkOperations.update(linkDetail.id, { url: linkDetail.url });
      if (workspaceSlug && projectId) {
        await fetchLinks(workspaceSlug, projectId, linkDetail.issue_id);
      }
    } finally {
      setIsRefreshing(false);
    }
  };

  // Rich card for providers we have provider metadata for (Figma, Google Drive).
  if (ProviderGlyph) {
    return (
      <div
        key={linkId}
        className="group 3xl:col-span-2 col-span-12 flex flex-shrink-0 flex-col overflow-hidden rounded-md border-[0.5px] border-subtle bg-surface-2 hover:bg-layer-1 lg:col-span-6 xl:col-span-4 2xl:col-span-3"
      >
        <a
          href={linkDetail.url}
          target="_blank"
          rel="noopener noreferrer"
          className="relative block h-24 w-full flex-shrink-0 overflow-hidden bg-layer-1"
        >
          {linkDetail.metadata?.thumbnail ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={linkDetail.metadata.thumbnail} alt="" className="h-full w-full object-cover" />
          ) : (
            <div className="flex h-full w-full items-center justify-center">
              <ProviderGlyph className="size-8 opacity-40" />
            </div>
          )}
          <span className="absolute left-2 top-2 inline-flex items-center gap-1 rounded-full bg-surface-1/90 px-2 py-0.5 text-caption-sm-medium text-secondary backdrop-blur-sm">
            <ProviderGlyph className="size-3 flex-shrink-0" />
            {linkDetail.metadata?.provider_name ?? provider}
          </span>
        </a>

        <div className="flex items-start justify-between gap-2 px-3 py-2">
          <div className="min-w-0 flex-1">
            <Tooltip tooltipContent={displayTitle} isMobile={isMobile}>
              <a
                href={linkDetail.url}
                target="_blank"
                rel="noopener noreferrer"
                className="block truncate text-body-xs-medium text-primary"
              >
                {displayTitle}
              </a>
            </Tooltip>
            <div className="mt-1 flex items-center gap-1 text-caption-sm-regular text-placeholder">
              <Tooltip tooltipContent={t("links.refresh")} isMobile={isMobile}>
                <button
                  type="button"
                  onClick={handleRefresh}
                  disabled={isRefreshing || isNotAllowed}
                  className="grid flex-shrink-0 place-items-center rounded-sm p-0.5 text-placeholder outline-none hover:bg-layer-1 hover:text-secondary disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <RefreshCw className={cn("size-3", isRefreshing && "animate-spin")} />
                </button>
              </Tooltip>
              <span className="truncate">
                {linkDetail.metadata?.crawled_at
                  ? t("links.synced_ago", { time: calculateTimeAgo(linkDetail.metadata.crawled_at) })
                  : t("links.not_synced_yet")}
              </span>
            </div>
          </div>

          <div className="flex flex-shrink-0 items-center gap-1">
            <span
              onClick={handleCopyLink}
              className="relative grid cursor-pointer place-items-center rounded-sm p-1 text-placeholder outline-none group-hover:text-secondary hover:bg-layer-1"
            >
              <CopyIcon className="h-3.5 w-3.5 stroke-[1.5]" />
            </span>
            <CustomMenu
              ellipsis
              buttonClassName="text-placeholder group-hover:text-secondary"
              placement="bottom-end"
              closeOnSelect
              disabled={isNotAllowed}
            >
              <CustomMenu.MenuItem
                className="flex items-center gap-2"
                onClick={() => {
                  toggleIssueLinkModal(true);
                }}
              >
                <EditIcon className="h-3 w-3 stroke-[1.5] text-secondary" />
                {t("common.actions.edit")}
              </CustomMenu.MenuItem>
              <CustomMenu.MenuItem
                className="flex items-center gap-2"
                onClick={() => {
                  linkOperations.remove(linkDetail.id);
                }}
              >
                <TrashIcon className="h-3 w-3" />
                {t("common.actions.delete")}
              </CustomMenu.MenuItem>
            </CustomMenu>
          </div>
        </div>
      </div>
    );
  }

  return (
    <>
      <div
        key={linkId}
        className="group 3xl:col-span-2 col-span-12 flex h-10 flex-shrink-0 items-center justify-between gap-3 rounded-sm border-[0.5px] border-subtle bg-surface-2 px-3 hover:bg-layer-1 lg:col-span-6 xl:col-span-4 2xl:col-span-3"
      >
        <div className="flex min-w-0 flex-1 items-center gap-2.5">
          {faviconUrl ? (
            <img src={faviconUrl} alt="favicon" className="size-4 flex-shrink-0" />
          ) : (
            <LinkIcon className="size-4 flex-shrink-0 text-tertiary group-hover:text-primary" />
          )}
          <Tooltip tooltipContent={linkDetail.url} isMobile={isMobile}>
            <a
              href={linkDetail.url}
              target="_blank"
              rel="noopener noreferrer"
              className="flex w-0 flex-1 cursor-pointer items-center text-body-xs-regular"
            >
              <span className="w-0 flex-1 truncate">
                {displayTitle}
                {linkTitle && linkTitle !== "" && (
                  <span className="text-caption-sm-regular text-placeholder"> {linkTitle}</span>
                )}
              </span>
            </a>
          </Tooltip>
        </div>
        <div className="flex flex-shrink-0 items-center gap-1">
          <p className="group-hover-text-secondary p-1 align-bottom text-caption-sm-regular leading-5 text-placeholder">
            {calculateTimeAgo(linkDetail.created_at)}
          </p>
          <span
            onClick={handleCopyLink}
            className="relative grid cursor-pointer place-items-center rounded-sm p-1 text-placeholder outline-none group-hover:text-secondary hover:bg-layer-1"
          >
            <CopyIcon className="h-3.5 w-3.5 stroke-[1.5]" />
          </span>
          <CustomMenu
            ellipsis
            buttonClassName="text-placeholder group-hover:text-secondary"
            placement="bottom-end"
            closeOnSelect
            disabled={isNotAllowed}
          >
            <CustomMenu.MenuItem
              className="flex items-center gap-2"
              onClick={() => {
                toggleIssueLinkModal(true);
              }}
            >
              <EditIcon className="h-3 w-3 stroke-[1.5] text-secondary" />
              {t("common.actions.edit")}
            </CustomMenu.MenuItem>
            <CustomMenu.MenuItem
              className="flex items-center gap-2"
              onClick={() => {
                linkOperations.remove(linkDetail.id);
              }}
            >
              <TrashIcon className="h-3 w-3" />
              {t("common.actions.delete")}
            </CustomMenu.MenuItem>
          </CustomMenu>
        </div>
      </div>
    </>
  );
});
