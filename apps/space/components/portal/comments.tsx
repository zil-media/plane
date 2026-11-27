/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { MessageSquare } from "lucide-react";
import useSWR from "swr";
// plane imports
import { Button } from "@plane/propel/button";
import { SitesPortalService } from "@plane/services";
import type { TZilPortalComment } from "@plane/types";
import { cn, getFileURL } from "@plane/utils";
// local imports
import { ago } from "./helpers";
import { PortalContent } from "./portal-content";

const portalService = new SitesPortalService();

type Props = {
  projectId: string;
  postId: string;
  /** a team member previewing: reads the conversation, answers from Ops */
  preview: boolean;
};

/** A copy of the space app's comment card (peek-overview/comment/comment-detail-card.tsx), read-only. */
function CommentRow({ comment, projectId }: { comment: TZilPortalComment; projectId: string }) {
  const avatar = comment.avatar_url ? getFileURL(comment.avatar_url) : undefined;
  const author = comment.is_mine ? "Vos" : comment.author;
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
          <div className="bg-gray-500 grid size-7 place-items-center rounded-full border-2 border-strong-1 text-on-color">
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
            {comment.is_team && <span className="text-tertiary"> · Equipo</span>}
          </div>
          <p className="mt-0.5 text-11 text-secondary">comentó {ago(comment.created_at)}</p>
        </div>
        <div className="issue-comments-section p-0">
          {/* through the read-only editor (its schema drops anything that is not content), never raw HTML */}
          <PortalContent id={comment.id} projectId={projectId} html={comment.html} />
        </div>
      </div>
    </div>
  );
}

/** The conversation with the team, and the box to write in it. */
export function PortalComments({ projectId, postId, preview }: Props) {
  const key = `PORTAL_COMMENTS_${projectId}_${postId}`;
  const { data, error: loadError, mutate } = useSWR(key, () => portalService.comments(projectId, postId));
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const send = async () => {
    const value = text.trim();
    if (!value || sending) return;
    setSending(true);
    setError(null);
    try {
      const created = await portalService.addComment(projectId, postId, value);
      // on top of what is cached now (and fetched again), never a list that lost the others
      await mutate((current) => ({ comments: [...(current?.comments ?? []), created] }));
      setText("");
    } catch {
      setError("No pudimos enviar tu comentario. Probá de nuevo.");
    } finally {
      setSending(false);
    }
  };

  const comments = data?.comments ?? [];
  return (
    <section className="space-y-4">
      <h4 className="font-medium">Comentarios</h4>
      {loadError ? (
        <p className="text-13 text-danger-primary">No pudimos cargar los comentarios.</p>
      ) : (
        data && comments.length === 0 && <p className="text-13 text-tertiary">Todavía no hay comentarios.</p>
      )}
      <div className="space-y-4">
        {comments.map((comment) => (
          <CommentRow key={comment.id} comment={comment} projectId={projectId} />
        ))}
      </div>
      {preview ? (
        <p className="rounded-md bg-layer-1 p-3 text-13 text-secondary">
          Estás viendo lo que ve el cliente. Respondé desde Zil Ops con un comentario externo.
        </p>
      ) : (
        <div className="space-y-2">
          <textarea
            value={text}
            onChange={(event) => setText(event.target.value)}
            placeholder="Escribí tu comentario"
            rows={3}
            maxLength={5000}
            className="w-full resize-none rounded-md border border-subtle bg-surface-1 p-3 text-13 text-primary placeholder:text-placeholder focus:border-accent-strong focus:outline-none"
          />
          {error && <p className="text-13 text-danger-primary">{error}</p>}
          <div className="flex justify-end">
            <Button
              variant="primary"
              onClick={send}
              disabled={!text.trim() || sending}
              className={cn(sending && "opacity-70")}
            >
              {sending ? "Enviando…" : "Enviar"}
            </Button>
          </div>
        </div>
      )}
    </section>
  );
}
