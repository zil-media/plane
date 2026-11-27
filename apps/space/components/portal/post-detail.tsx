/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { Fragment, useCallback, useEffect, useRef, useState } from "react";
import { Dialog, Transition } from "@headlessui/react";
import { Clapperboard, ExternalLink, MoveRight } from "lucide-react";
import useSWR from "swr";
// plane imports
import { useTranslation } from "@plane/i18n";
import { DueDatePropertyIcon, LabelPropertyIcon, StateGroupIcon, StatePropertyIcon } from "@plane/propel/icons";
import { SitesPortalService } from "@plane/services";
import { Loader } from "@plane/ui";
import type { TZilPortalComment, TZilPortalMedia } from "@plane/types";
import { getFileURL } from "@plane/utils";
// local imports
import { PortalComments } from "./comments";
import type { TPortalPlayback } from "./comments";
import { dateLocale, dayLabel, isVideo } from "./helpers";
import { PortalContent } from "./portal-content";
import { PortalVideoPlayer } from "./video-player";
import type { TVideoMarker } from "./video-player";

const portalService = new SitesPortalService();

/** A comment's text, plain, for its mark's hover. */
const plainText = (html: string) =>
  typeof window === "undefined"
    ? ""
    : (new DOMParser().parseFromString(html, "text/html").body.textContent ?? "").trim();

/** The marks of one video's timeline: the comments pinned to a second of it. */
const markersOf = (comments: TZilPortalComment[] | undefined, media: string): TVideoMarker[] =>
  (comments ?? [])
    .filter((comment) => comment.moment?.media === media)
    .map((comment) => ({
      id: comment.id,
      at: comment.moment?.at ?? 0,
      author: comment.author,
      text: plainText(comment.html),
    }));

/** One image or video of the post: uploaded to Ops or a Drive file streamed by Ops, or, when Ops
 * can't play a Drive file right now, a "being processed" card (the team gets the warning in Ops). */
function PostMediaItem({
  item,
  markers,
  activeMarker,
  onPlayer,
  onTime,
  onMarker,
}: {
  item: TZilPortalMedia;
  markers: TVideoMarker[];
  activeMarker: string | null;
  onPlayer: (element: HTMLVideoElement | null) => void;
  onTime: (seconds: number) => void;
  onMarker: (marker: TVideoMarker) => void;
}) {
  const { t } = useTranslation();
  if (item.kind === "unavailable")
    return (
      <div className="flex aspect-video w-full flex-col items-center justify-center gap-2 p-6 text-center">
        <Clapperboard className="size-6 text-tertiary" aria-hidden="true" />
        <p className="text-14 font-medium text-primary">{t("zil_portal.video_processing_title")}</p>
        <p className="text-13 text-tertiary">{t("zil_portal.video_processing_text")}</p>
      </div>
    );
  // uploaded to Ops or a Drive file, both come through Ops' own portal API
  const src = getFileURL(item.url);
  if (isVideo(item.type))
    return (
      <PortalVideoPlayer
        src={src}
        name={item.name}
        markers={markers}
        activeMarker={activeMarker}
        onPlayer={onPlayer}
        onTime={onTime}
        onMarker={onMarker}
      />
    );
  return <img src={src} alt={item.name} className="max-h-[60vh] w-full object-contain" />;
}

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
  // the post's players, and where the one last played is: a comment can point at that second
  const players = useRef<Record<string, HTMLVideoElement | null>>({});
  const [current, setCurrent] = useState<TPortalPlayback["current"]>(null);
  // the comment whose mark was picked: it stands out in the conversation
  const [focused, setFocused] = useState<string | null>(null);
  useEffect(() => {
    setCurrent(null);
    setFocused(null);
  }, [postId]);
  // the same conversation the comments below show (one request, shared): the timelines' marks
  const { data: conversation } = useSWR(postId ? `PORTAL_COMMENTS_${projectId}_${postId}` : null, () =>
    portalService.comments(projectId, postId as string)
  );

  const track = (item: TZilPortalMedia) => (seconds: number) => {
    const at = Math.floor(seconds);
    setCurrent((now) => (now?.media === item.id && now.at === at ? now : { media: item.id, name: item.name, at }));
  };
  const seek = useCallback((media: string, at: number, scroll = true) => {
    const player = players.current[media];
    if (!player) return;
    player.currentTime = at;
    if (scroll) player.scrollIntoView({ behavior: "smooth", block: "center" });
    void player.play().catch(() => undefined);
  }, []);
  const pause = useCallback(() => {
    if (current) players.current[current.media]?.pause();
  }, [current]);
  // the videos the portal plays itself (Drive's preview can't jump to a second)
  const playable = new Set(
    (post?.media ?? []).filter((item) => item.kind !== "unavailable" && isVideo(item.type)).map((item) => item.id)
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
                          {post.media.map((item) => (
                            <div
                              key={item.id}
                              className="w-full flex-shrink-0 snap-center overflow-hidden rounded-md bg-layer-1"
                            >
                              <PostMediaItem
                                item={item}
                                markers={markersOf(conversation?.comments, item.id)}
                                activeMarker={focused}
                                onPlayer={(element) => {
                                  players.current[item.id] = element;
                                }}
                                onTime={track(item)}
                                onMarker={(marker) => {
                                  seek(item.id, marker.at, false);
                                  setFocused(marker.id);
                                }}
                              />
                            </div>
                          ))}
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
                      <PortalComments
                        key={post.id}
                        projectId={projectId}
                        postId={post.id}
                        preview={preview}
                        playback={{ current, playable, seek, pause, focused }}
                      />
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
