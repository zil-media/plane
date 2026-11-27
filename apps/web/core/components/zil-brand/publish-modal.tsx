/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { TriangleAlert } from "lucide-react";
import useSWR from "swr";
// plane imports
import { useTranslation } from "@plane/i18n";
import { Button } from "@plane/propel/button";
import { CloseIcon } from "@plane/propel/icons";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import { Checkbox, EModalPosition, EModalWidth, Loader, ModalCore } from "@plane/ui";
import { renderFormattedDate } from "@plane/utils";
// services
import { ZilBrandService } from "@/services/zil-brand.service";

const zilBrandService = new ZilBrandService();

type Props = {
  workspaceSlug: string;
  projectId: string;
  isOpen: boolean;
  /** what the client gets per post, for the note under the list */
  changeRounds: number;
  changeDays: number;
  onClose: () => void;
};

/**
 * "Publicar al cliente", a copy of Ops' transfer modal (cycles/transfer-issues-modal.tsx): the posts
 * marked "Visible al cliente", the team ticks which go out now. The client sees them from then on, gets
 * one email, and their time for changes starts. Already published ones show when; a post without a video
 * or image says so.
 */
export function ZilPublishModal({ workspaceSlug, projectId, isOpen, changeRounds, changeDays, onClose }: Props) {
  const { t } = useTranslation();
  const key = isOpen ? `ZIL_PUBLISH_${projectId}` : null;
  const { data, isLoading, mutate } = useSWR(key, () => zilBrandService.getPublishable(workspaceSlug, projectId));
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const [publishing, setPublishing] = useState(false);
  const posts = data?.posts ?? [];

  const close = () => {
    setChosen(new Set());
    onClose();
  };

  const toggle = (id: string) =>
    setChosen((now) => {
      const next = new Set(now);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const publish = async () => {
    setPublishing(true);
    try {
      const { published } = await zilBrandService.publishPosts(workspaceSlug, projectId, [...chosen]);
      setToast({ type: TOAST_TYPE.SUCCESS, title: t("zil_brand.publish_done", { count: published }) });
      await mutate();
      close();
    } catch {
      setToast({ type: TOAST_TYPE.ERROR, title: t("toast.error"), message: t("zil_brand.portal_error") });
    } finally {
      setPublishing(false);
    }
  };

  return (
    <ModalCore isOpen={isOpen} handleClose={close} position={EModalPosition.TOP} width={EModalWidth.XXL}>
      <div className="flex flex-col gap-4 py-5">
        <div className="flex items-center justify-between px-5">
          <h4 className="text-18 font-medium text-primary">{t("zil_brand.publish_title")}</h4>
          <button type="button" onClick={close} aria-label={t("close")}>
            <CloseIcon className="h-4 w-4" />
          </button>
        </div>
        <p className="px-5 text-13 text-secondary">{t("zil_brand.publish_description")}</p>
        <div className="flex max-h-[50vh] w-full flex-col gap-1 overflow-y-auto px-5">
          {isLoading ? (
            <Loader className="space-y-2">
              <Loader.Item height="40px" />
              <Loader.Item height="40px" />
            </Loader>
          ) : posts.length === 0 ? (
            <p className="py-6 text-center text-13 text-secondary">{t("zil_brand.publish_empty")}</p>
          ) : (
            posts.map((post) => {
              const published = !!post.published_at;
              return (
                <label
                  key={post.id}
                  htmlFor={`publish-${post.id}`}
                  className="flex w-full cursor-pointer items-center gap-3 rounded-sm px-3 py-2 text-13 text-secondary hover:bg-surface-2 has-[:disabled]:cursor-default has-[:disabled]:opacity-60"
                >
                  <Checkbox
                    id={`publish-${post.id}`}
                    checked={published || chosen.has(post.id)}
                    disabled={published}
                    onChange={() => toggle(post.id)}
                  />
                  <span
                    className="size-2 flex-shrink-0 rounded-full"
                    style={{ backgroundColor: post.state_color ?? undefined }}
                  />
                  <span className="min-w-0 flex-1 truncate text-primary">{post.name}</span>
                  {!post.has_media && !published && (
                    <span className="flex flex-shrink-0 items-center gap-1 text-11 text-warning-primary">
                      <TriangleAlert className="size-3" aria-hidden="true" />
                      {t("zil_brand.publish_no_media")}
                    </span>
                  )}
                  <span className="flex-shrink-0 text-11 text-tertiary tabular-nums">
                    {published
                      ? t("zil_brand.publish_published_on", { date: renderFormattedDate(post.published_at) ?? "" })
                      : [post.target_date ? renderFormattedDate(post.target_date) : null, post.target_time]
                          .filter(Boolean)
                          .join(" · ")}
                  </span>
                </label>
              );
            })
          )}
        </div>
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-subtle px-5 pt-4">
          <span className="text-11 text-tertiary">
            {t("zil_brand.publish_terms", { rounds: changeRounds, days: changeDays })}
          </span>
          <div className="flex gap-2">
            <Button variant="secondary" onClick={close}>
              {t("cancel")}
            </Button>
            <Button variant="primary" onClick={() => void publish()} disabled={chosen.size === 0 || publishing}>
              {t("zil_brand.publish_submit", { count: chosen.size })}
            </Button>
          </div>
        </div>
      </div>
    </ModalCore>
  );
}
