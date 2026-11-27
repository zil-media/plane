/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useMemo } from "react";
import { observer } from "mobx-react";
import { useParams } from "next/navigation";
import useSWR from "swr";
// plane imports
import { useTranslation } from "@plane/i18n";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import { EFileAssetType } from "@plane/types";
import type { TCommentsOperations, TIssueComment } from "@plane/types";
import { copyTextToClipboard } from "@plane/utils";
// components
import { CommentsWrapper } from "@/components/comments/comments";
// hooks
import { useEditorAsset } from "@/hooks/store/use-editor-asset";
// services
import { ZilBrandService } from "@/services/zil-brand.service";
// store
import type { TPageInstance } from "@/store/pages/base-page";

const zilBrandService = new ZilBrandService();

type Props = {
  page: TPageInstance;
};

/**
 * The conversation with the brand's clients on a page of the "Cliente" folder: the same comments
 * Ops shows on a work item (CommentsWrapper), all of them seen by the client in the portal.
 */
export const PageNavigationPaneClientTabPanel = observer(function PageNavigationPaneClientTabPanel({ page }: Props) {
  const { t } = useTranslation();
  const { workspaceSlug, projectId } = useParams<{ workspaceSlug?: string; projectId?: string }>();
  const pageId = page.id;
  const { uploadEditorAsset, duplicateEditorAsset } = useEditorAsset();
  const key = workspaceSlug && projectId && pageId ? `ZIL_PAGE_CLIENT_COMMENTS_${pageId}` : null;
  const { data: comments, mutate } = useSWR(key, () =>
    zilBrandService.listPageClientComments(workspaceSlug as string, projectId as string, pageId as string)
  );

  const operations: TCommentsOperations = useMemo(() => {
    const fail = (message: string) => setToast({ type: TOAST_TYPE.ERROR, title: t("toast.error"), message });
    const ready = () => !!workspaceSlug && !!projectId && !!pageId;
    return {
      copyCommentLink: () => void copyTextToClipboard(window.location.href),
      createComment: async (data) => {
        if (!ready()) return undefined;
        try {
          const created = await zilBrandService.createPageClientComment(
            workspaceSlug as string,
            projectId as string,
            pageId as string,
            { comment_html: data.comment_html }
          );
          await mutate((current) => [...(current ?? []), created], { revalidate: false });
          return created;
        } catch {
          fail(t("zil_brand.portal_error"));
          return undefined;
        }
      },
      updateComment: async (commentId, data) => {
        if (!ready()) return;
        try {
          const updated = await zilBrandService.updatePageClientComment(
            workspaceSlug as string,
            projectId as string,
            pageId as string,
            commentId,
            { comment_html: data.comment_html }
          );
          await mutate((current) => (current ?? []).map((c) => (c.id === commentId ? updated : c)), {
            revalidate: false,
          });
        } catch {
          fail(t("zil_brand.portal_error"));
        }
      },
      removeComment: async (commentId) => {
        if (!ready()) return;
        try {
          await zilBrandService.deletePageClientComment(
            workspaceSlug as string,
            projectId as string,
            pageId as string,
            commentId
          );
          await mutate((current) => (current ?? []).filter((c) => c.id !== commentId), { revalidate: false });
        } catch {
          fail(t("zil_brand.portal_error"));
        }
      },
      // images go with the page (the portal opens a page's images for its clients)
      uploadCommentAsset: async (blockId, file) =>
        uploadEditorAsset({
          blockId,
          data: { entity_identifier: pageId ?? "", entity_type: EFileAssetType.PAGE_DESCRIPTION },
          file,
          projectId: projectId as string,
          workspaceSlug: workspaceSlug as string,
        }),
      duplicateCommentAsset: async (assetId) =>
        duplicateEditorAsset({
          assetId,
          entityId: pageId ?? undefined,
          entityType: EFileAssetType.PAGE_DESCRIPTION,
          projectId: projectId as string,
          workspaceSlug: workspaceSlug as string,
        }),
      // no reactions on this conversation
      addCommentReaction: async () => {},
      deleteCommentReaction: async () => {},
      react: async () => {},
      reactionIds: () => undefined,
      userReactions: () => undefined,
      getReactionUsers: () => "",
    };
  }, [workspaceSlug, projectId, pageId, mutate, t, uploadEditorAsset, duplicateEditorAsset]);

  return (
    <div className="flex h-full flex-col gap-2 overflow-hidden px-3.5">
      <p className="text-11 text-tertiary">{t("zil_brand.client_tab_hint")}</p>
      {pageId && (
        <CommentsWrapper
          entityId={pageId}
          projectId={projectId}
          activityOperations={operations}
          comments={(comments ?? []) as TIssueComment[]}
          showAccessSpecifier={false}
        />
      )}
    </div>
  );
});
