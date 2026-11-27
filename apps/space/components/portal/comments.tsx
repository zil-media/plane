/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { MessageSquare, Play } from "lucide-react";
import useSWR from "swr";
// plane imports
import { useTranslation } from "@plane/i18n";
import { Button } from "@plane/propel/button";
import { SitesPortalService } from "@plane/services";
import type { TZilPortalComment } from "@plane/types";
import { Checkbox } from "@plane/ui";
import { cn, getFileURL } from "@plane/utils";
// local imports
import { ago, clock, dateLocale } from "./helpers";
import { PortalContent } from "./portal-content";

const portalService = new SitesPortalService();

/** A post's videos, for comments that point at a second of one of them. */
export type TPortalPlayback = {
  /** where the video last played is */
  current: { media: string; name: string; at: number } | null;
  /** the videos a moment can jump to */
  playable: Set<string>;
  seek: (media: string, at: number) => void;
  pause: () => void;
};

type Props = {
  projectId: string;
  /** the conversation of a post, or of a document of the "Cliente" folder */
  postId?: string;
  documentId?: string;
  /** a team member previewing: reads the conversation, answers from Ops */
  preview: boolean;
  playback?: TPortalPlayback;
};

/** A copy of the space app's comment card (peek-overview/comment/comment-detail-card.tsx), read-only. */
function CommentRow({
  comment,
  projectId,
  playback,
}: {
  comment: TZilPortalComment;
  projectId: string;
  playback?: TPortalPlayback;
}) {
  const { t, currentLocale } = useTranslation();
  const avatar = comment.avatar_url ? getFileURL(comment.avatar_url) : undefined;
  const author = comment.is_mine ? t("zil_portal.you") : comment.author;
  return (
    <div className="relative flex items-start space-x-3">
      <div className="relative px-1">
        {avatar ? (
          <img
            src={avatar}
            alt={comment.author}
            height={30}
            width={30}
            className="grid size-7 place-items-center rounded-full border-2 border-strong-1"
          />
        ) : (
          <div className="grid size-7 place-items-center rounded-full border-2 border-strong-1 bg-layer-3 text-11 text-secondary">
            {comment.author.charAt(0).toUpperCase()}
          </div>
        )}
        <span className="absolute -right-1 -bottom-0.5 rounded-tl-sm bg-layer-1 px-0.5 py-px">
          <MessageSquare className="size-3 text-secondary" aria-hidden="true" strokeWidth={2} />
        </span>
      </div>
      <div className="min-w-0 flex-1">
        <div>
          <div className="text-11">
            {author}
            {comment.is_team && <span className="text-tertiary"> · {t("zil_portal.team")}</span>}
          </div>
          <p className="mt-0.5 text-11 text-secondary">
            {t("zil_portal.commented_ago", { ago: ago(comment.created_at, dateLocale(currentLocale)) })}
          </p>
        </div>
        {comment.moment && (
          <button
            type="button"
            onClick={() => comment.moment && playback?.seek(comment.moment.media, comment.moment.at)}
            disabled={!playback?.playable.has(comment.moment.media)}
            aria-label={t("zil_portal.go_to_moment", { time: comment.moment.label })}
            className="mt-1 inline-flex items-center gap-1 rounded-sm bg-accent-subtle px-1.5 py-0.5 text-11 font-medium text-accent-primary hover:bg-accent-subtle-hover disabled:cursor-default disabled:opacity-60"
          >
            <Play className="size-3" aria-hidden="true" />
            {comment.moment.label}
          </button>
        )}
        <div className="issue-comments-section p-0">
          {/* through the read-only editor (its schema drops anything that is not content), never raw HTML */}
          <PortalContent id={comment.id} projectId={projectId} html={comment.html} />
        </div>
      </div>
    </div>
  );
}

/** The conversation with the team, and the box to write in it. */
export function PortalComments({ projectId, postId, documentId, preview, playback }: Props) {
  const { t } = useTranslation();
  const key = documentId ? `PORTAL_DOC_COMMENTS_${projectId}_${documentId}` : `PORTAL_COMMENTS_${projectId}_${postId}`;
  const load = () =>
    documentId
      ? portalService.documentComments(projectId, documentId)
      : portalService.comments(projectId, postId ?? "");
  const { data, error: loadError, mutate } = useSWR(key, load);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // pinned to where the video is, once one has played (the client can untick it)
  const [atMoment, setAtMoment] = useState(true);
  const moment = playback?.current && playback.playable.has(playback.current.media) ? playback.current : null;

  const send = async () => {
    const value = text.trim();
    if (!value || sending) return;
    setSending(true);
    setError(null);
    try {
      const created = documentId
        ? await portalService.addDocumentComment(projectId, documentId, value)
        : await portalService.addComment(
            projectId,
            postId ?? "",
            value,
            moment && atMoment ? { media: moment.media, at: moment.at } : undefined
          );
      // on top of what is cached now (and fetched again), never a list that lost the others
      await mutate((current) => ({ comments: [...(current?.comments ?? []), created] }));
      setText("");
    } catch {
      setError(t("zil_portal.send_error"));
    } finally {
      setSending(false);
    }
  };

  const comments = data?.comments ?? [];
  return (
    <section className="space-y-4">
      <h4 className="font-medium">{t("zil_portal.comments")}</h4>
      {loadError ? (
        <p className="text-13 text-danger-primary">{t("zil_portal.comments_load_error")}</p>
      ) : (
        data && comments.length === 0 && <p className="text-13 text-tertiary">{t("zil_portal.no_comments")}</p>
      )}
      <div className="space-y-4">
        {comments.map((comment) => (
          <CommentRow key={comment.id} comment={comment} projectId={projectId} playback={playback} />
        ))}
      </div>
      {preview ? (
        <p className="rounded-md bg-layer-1 p-3 text-13 text-secondary">{t("zil_portal.preview_answer_from_ops")}</p>
      ) : (
        <div className="space-y-2">
          <textarea
            value={text}
            onChange={(event) => setText(event.target.value)}
            // writing about a moment: the video stops there
            onFocus={() => playback?.pause()}
            placeholder={t("zil_portal.comment_placeholder")}
            rows={3}
            maxLength={5000}
            className="w-full resize-none rounded-md border border-subtle bg-surface-1 p-3 text-13 text-primary placeholder:text-placeholder focus:border-accent-strong focus:outline-none"
          />
          {moment && (
            <label className="flex cursor-pointer items-center gap-2 text-13 text-secondary">
              <Checkbox checked={atMoment} onChange={(event) => setAtMoment(event.target.checked)} />
              {t("zil_portal.comment_at", { time: clock(moment.at), name: moment.name })}
            </label>
          )}
          {error && <p className="text-13 text-danger-primary">{error}</p>}
          <div className="flex justify-end">
            <Button
              variant="primary"
              onClick={send}
              disabled={!text.trim() || sending}
              className={cn(sending && "opacity-70")}
            >
              {sending ? t("zil_portal.sending") : t("zil_portal.send")}
            </Button>
          </div>
        </div>
      )}
    </section>
  );
}
