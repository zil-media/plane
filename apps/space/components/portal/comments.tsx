/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import useSWR from "swr";
// plane imports
import { Button } from "@plane/propel/button";
import { SitesPortalService } from "@plane/services";
import type { TZilPortalComment } from "@plane/types";
import { cn, getFileURL } from "@plane/utils";
// local imports
import { ago } from "./helpers";

const portalService = new SitesPortalService();

type Props = {
  projectId: string;
  postId: string;
  /** a team member previewing: reads the conversation, answers from Ops */
  preview: boolean;
};

function CommentRow({ comment }: { comment: TZilPortalComment }) {
  const avatar = comment.avatar_url ? getFileURL(comment.avatar_url) : undefined;
  return (
    <div className="flex items-start gap-3">
      {avatar ? (
        <img src={avatar} alt={comment.author} className="size-7 flex-shrink-0 rounded-full object-cover" />
      ) : (
        <div className="grid size-7 flex-shrink-0 place-items-center rounded-full bg-layer-1 text-11 text-secondary uppercase">
          {comment.author.charAt(0)}
        </div>
      )}
      <div className="min-w-0 flex-1">
        <p className="text-11 text-secondary">
          <span className="font-medium text-primary">{comment.is_mine ? "Vos" : comment.author}</span>
          {comment.is_team && " · Equipo"} · {ago(comment.created_at)}
        </p>
        <div
          className="mt-1 text-13 break-words text-primary [&_p]:min-h-[1em]"
          // built by the API: the client's text escaped, or an external comment the team wrote in Ops
          dangerouslySetInnerHTML={{ __html: comment.html }}
        />
      </div>
    </div>
  );
}

/** The conversation with the team, and the box to write in it. */
export function PortalComments({ projectId, postId, preview }: Props) {
  const key = `PORTAL_COMMENTS_${postId}`;
  const { data, mutate } = useSWR(key, () => portalService.comments(projectId, postId));
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
      await mutate({ comments: [...(data?.comments ?? []), created] }, { revalidate: false });
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
      <h3 className="text-14 font-semibold text-primary">Comentarios</h3>
      {comments.length === 0 && <p className="text-13 text-tertiary">Todavía no hay comentarios.</p>}
      <div className="space-y-4">
        {comments.map((comment) => (
          <CommentRow key={comment.id} comment={comment} />
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
