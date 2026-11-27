/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { Fragment } from "react";
import { Dialog, Transition } from "@headlessui/react";
import { ExternalLink, MoveRight } from "lucide-react";
import useSWR from "swr";
// plane imports
import { useTranslation } from "@plane/i18n";
import { DueDatePropertyIcon, LabelPropertyIcon, StateGroupIcon, StatePropertyIcon } from "@plane/propel/icons";
import { SitesPortalService } from "@plane/services";
import { Loader } from "@plane/ui";
import { getFileURL } from "@plane/utils";
// local imports
import { PortalComments } from "./comments";
import { dateLocale, dayLabel, isVideo } from "./helpers";
import { PortalContent } from "./portal-content";

const portalService = new SitesPortalService();

type Props = {
  projectId: string;
  postId: string | null;
  preview: boolean;
  onClose: () => void;
};

/**
 * A post as the client sees it: a copy of the space app's work item peek in "modal" mode
 * (components/issues/peek-overview/layout.tsx + side-peek-view.tsx): header, title and copy, the
 * properties rows (estado, fecha, red/formato), divider, comments. Media go above the copy, big.
 */
export function PortalPostDetail({ projectId, postId, preview, onClose }: Props) {
  const { t, currentLocale } = useTranslation();
  const { data: post, error } = useSWR(postId ? `PORTAL_POST_${projectId}_${postId}` : null, () =>
    portalService.retrievePost(projectId, postId as string)
  );

  return (
    <Transition.Root appear show={!!postId} as={Fragment}>
      <Dialog as="div" onClose={onClose}>
        <Transition.Child
          as={Fragment}
          enter="ease-out duration-300"
          enterFrom="opacity-0"
          enterTo="opacity-100"
          leave="ease-in duration-200"
          leaveFrom="opacity-100"
          leaveTo="opacity-0"
        >
          <div className="fixed inset-0 z-20 bg-backdrop transition-opacity" />
        </Transition.Child>
        <Transition.Child
          as={Fragment}
          enter="ease-out duration-300"
          enterFrom="opacity-0"
          enterTo="opacity-100"
          leave="ease-in duration-200"
          leaveFrom="opacity-100"
          leaveTo="opacity-0"
        >
          <Dialog.Panel>
            {/* the peek's modal size on a computer; the whole screen on a phone */}
            <div className="fixed inset-0 z-20 bg-surface-1 transition-all duration-300 md:inset-auto md:top-1/2 md:left-1/2 md:h-[80%] md:w-3/5 md:-translate-x-1/2 md:-translate-y-1/2 md:rounded-lg">
              <div className="flex size-full flex-col overflow-hidden">
                {/* header (PeekOverviewHeader) */}
                <div className="w-full p-5">
                  <div className="flex items-center justify-between">
                    <button
                      type="button"
                      onClick={onClose}
                      aria-label={t("zil_portal.close")}
                      className="text-tertiary hover:text-secondary"
                    >
                      <MoveRight className="size-4" />
                    </button>
                  </div>
                </div>
                {error ? (
                  <p className="px-6 text-13 text-tertiary">{t("zil_portal.post_unavailable")}</p>
                ) : post ? (
                  <div className="size-full overflow-y-auto px-6">
                    {/* title and copy (PeekOverviewIssueDetails) */}
                    <div className="w-full space-y-2">
                      <Dialog.Title as="h4" className="text-20 font-medium break-words">
                        {post.name}
                      </Dialog.Title>
                      {post.media.length > 0 && (
                        <div className="flex snap-x snap-mandatory gap-2 overflow-x-auto py-2">
                          {post.media.map((item) => {
                            const src = getFileURL(item.url);
                            return (
                              <div
                                key={item.id}
                                className="w-full flex-shrink-0 snap-center overflow-hidden rounded-md bg-layer-1"
                              >
                                {isVideo(item.type) ? (
                                  <video src={src} controls className="max-h-[60vh] w-full object-contain">
                                    <track kind="captions" />
                                  </video>
                                ) : (
                                  <img src={src} alt={item.name} className="max-h-[60vh] w-full object-contain" />
                                )}
                              </div>
                            );
                          })}
                        </div>
                      )}
                      <PortalContent id={post.id} projectId={projectId} html={post.description_html} />
                      {post.links.length > 0 && (
                        <ul className="space-y-1">
                          {post.links.map((link) => (
                            <li key={link.url}>
                              <a
                                href={link.url}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="inline-flex items-center gap-1 text-13 text-accent-primary hover:underline"
                              >
                                <ExternalLink className="size-3.5" />
                                {link.title}
                              </a>
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                    {/* properties (PeekOverviewIssueProperties) */}
                    <div className="mt-6 w-full space-y-2">
                      <div className="flex h-8 items-center gap-3">
                        <div className="flex w-2/5 flex-shrink-0 items-center gap-1 text-13 text-tertiary sm:w-1/4">
                          <StatePropertyIcon className="size-4 flex-shrink-0" />
                          <span>{t("common.state")}</span>
                        </div>
                        <div className="flex min-w-0 flex-1 items-center gap-1.5 py-0.5 text-13">
                          <StateGroupIcon
                            stateGroup={post.status === "published" ? "completed" : "started"}
                            color={post.status_color ?? undefined}
                          />
                          {t(`zil_portal.status.${post.status}`)}
                        </div>
                      </div>
                      <div className="flex h-8 items-center gap-3">
                        <div className="flex w-2/5 flex-shrink-0 items-center gap-1 text-13 text-tertiary sm:w-1/4">
                          <DueDatePropertyIcon className="size-4 flex-shrink-0" />
                          <span>{t("zil_portal.publish_date")}</span>
                        </div>
                        <div className="min-w-0 flex-1 text-13 first-letter:uppercase">
                          {post.publish_date ? (
                            dayLabel(post.publish_date, dateLocale(currentLocale))
                          ) : (
                            <span className="text-secondary">{t("zil_portal.to_define")}</span>
                          )}
                        </div>
                      </div>
                      {post.labels.length > 0 && (
                        <div className="flex min-h-8 items-start gap-3">
                          <div className="flex h-8 w-2/5 flex-shrink-0 items-center gap-1 text-13 text-tertiary sm:w-1/4">
                            <LabelPropertyIcon className="size-4 flex-shrink-0" />
                            <span>{t("zil_portal.network_format")}</span>
                          </div>
                          <div className="flex min-w-0 flex-1 flex-wrap gap-1 py-1.5">
                            {post.labels.map((label) => (
                              <span
                                key={label.name}
                                className="inline-flex items-center gap-1 rounded-sm border border-subtle px-1.5 py-0.5 text-11 text-secondary"
                              >
                                <span className="size-1.5 rounded-full" style={{ backgroundColor: label.color }} />
                                {label.name}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                    {/* divider */}
                    <div className="my-5 h-[1] w-full border-t border-subtle" />
                    {/* comments (PeekOverviewIssueActivity) */}
                    <div className="w-full pb-5">
                      <PortalComments key={post.id} projectId={projectId} postId={post.id} preview={preview} />
                    </div>
                  </div>
                ) : (
                  <Loader className="px-6">
                    <Loader.Item height="30px" />
                    <div className="mt-3 space-y-2">
                      <Loader.Item height="20px" width="70%" />
                      <Loader.Item height="20px" width="60%" />
                      <Loader.Item height="20px" width="60%" />
                    </div>
                  </Loader>
                )}
              </div>
            </div>
          </Dialog.Panel>
        </Transition.Child>
      </Dialog>
    </Transition.Root>
  );
}
