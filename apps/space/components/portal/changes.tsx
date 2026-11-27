/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useState } from "react";
import { Clock, Pencil, Play, Trash2 } from "lucide-react";
import useSWR from "swr";
// plane imports
import { useTranslation } from "@plane/i18n";
import { Button } from "@plane/propel/button";
import { SitesPortalService } from "@plane/services";
import type { TZilPortalComment, TZilPortalDraft, TZilPortalReview } from "@plane/types";
import { AlertModalCore, Checkbox } from "@plane/ui";
import { cn } from "@plane/utils";
// local imports
import type { TPortalPlayback } from "./comments";
import { clock, remaining } from "./helpers";

const portalService = new SitesPortalService();

export const draftsKey = (projectId: string, postId: string) => `PORTAL_DRAFTS_${projectId}_${postId}`;

const TEXTAREA =
  "w-full resize-none rounded-md border border-subtle bg-surface-1 p-3 text-13 text-primary placeholder:text-placeholder focus:border-accent-strong focus:outline-none";

/** Ticks every 30 s, so the time left counts down while the post is open. */
function useNow() {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 30_000);
    return () => window.clearInterval(timer);
  }, []);
  return now;
}

/** The post's rounds of changes left and the time left to ask for them, or why changes are closed. */
export function ReviewBanner({ review }: { review: TZilPortalReview }) {
  const { t } = useTranslation();
  const now = useNow();
  const left = review.deadline ? new Date(review.deadline).getTime() - now : null;
  const reason = review.open && left !== null && left <= 0 ? "expired" : review.reason;
  if (reason)
    return (
      <p className="flex items-center gap-2 rounded-md bg-layer-1 px-3 py-2 text-13 text-secondary">
        <Clock className="size-3.5 flex-shrink-0" aria-hidden="true" />
        {t(`zil_portal.changes_closed.${reason}`)}
      </p>
    );
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-md bg-accent-subtle px-3 py-2 text-13 text-primary">
      <span className="font-medium">
        {review.left === null
          ? t("zil_portal.rounds_unlimited")
          : t("zil_portal.rounds_left", { left: review.left, rounds: review.rounds ?? 0 })}
      </span>
      {left !== null && (
        <span className="flex items-center gap-1 text-secondary">
          <Clock className="size-3.5" aria-hidden="true" />
          {t("zil_portal.time_left", { time: remaining(left) })}
        </span>
      )}
    </div>
  );
}

/** One change the client is writing: its moment of the video, its text, and edit / delete. */
export function DraftRow({
  draft,
  playback,
  onSave,
  onDelete,
}: {
  draft: TZilPortalDraft;
  playback?: TPortalPlayback;
  onSave: (text: string) => Promise<void>;
  onDelete: () => Promise<void>;
}) {
  const { t } = useTranslation();
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(draft.text);
  const [busy, setBusy] = useState(false);
  const run = async (action: () => Promise<void>) => {
    setBusy(true);
    try {
      await action();
    } finally {
      setBusy(false);
    }
  };
  return (
    <li className="flex items-start gap-3 rounded-md border border-dashed border-subtle p-3">
      <div className="min-w-0 flex-1 space-y-1">
        {draft.moment && (
          <button
            type="button"
            onClick={() => draft.moment && playback?.seek(draft.moment.media, draft.moment.at)}
            disabled={!playback?.playable.has(draft.moment.media)}
            aria-label={t("zil_portal.go_to_moment", { time: draft.moment.label })}
            className="inline-flex items-center gap-1 rounded-sm bg-accent-subtle px-1.5 py-0.5 text-11 font-medium text-accent-primary hover:bg-accent-subtle-hover disabled:cursor-default disabled:opacity-60"
          >
            <Play className="size-3" aria-hidden="true" />
            {draft.moment.label}
          </button>
        )}
        {editing ? (
          <div className="space-y-2">
            <textarea
              value={text}
              onChange={(event) => setText(event.target.value)}
              rows={2}
              maxLength={5000}
              className={TEXTAREA}
            />
            <div className="flex justify-end gap-2">
              <Button
                variant="secondary"
                size="sm"
                onClick={() => {
                  setText(draft.text);
                  setEditing(false);
                }}
              >
                {t("cancel")}
              </Button>
              <Button
                variant="primary"
                size="sm"
                disabled={!text.trim() || busy}
                onClick={() => void run(() => onSave(text.trim()).then(() => setEditing(false)))}
              >
                {t("save")}
              </Button>
            </div>
          </div>
        ) : (
          <p className="text-13 whitespace-pre-wrap text-primary">{draft.text}</p>
        )}
      </div>
      {!editing && (
        <div className="flex flex-shrink-0 items-center gap-1 text-tertiary">
          <button
            type="button"
            onClick={() => setEditing(true)}
            aria-label={t("edit")}
            className="rounded-sm p-1 hover:bg-layer-1 hover:text-secondary"
          >
            <Pencil className="size-3.5" />
          </button>
          <button
            type="button"
            onClick={() => void run(onDelete)}
            disabled={busy}
            aria-label={t("delete")}
            className="rounded-sm p-1 hover:bg-layer-1 hover:text-danger-primary"
          >
            <Trash2 className="size-3.5" />
          </button>
        </div>
      )}
    </li>
  );
}

type Props = {
  projectId: string;
  postId: string;
  review: TZilPortalReview;
  playback?: TPortalPlayback;
  /** a round went out: its comments and what is left */
  onSent: (comments: TZilPortalComment[], review: TZilPortalReview) => Promise<void> | void;
};

/**
 * The client's changes on a post: they write them as drafts (only they see them, each optionally at
 * a second of the video), and "Enviar cambios" sends them all to the team as one round, after
 * confirming what is left. Only while the post's window is open.
 */
export function PortalChanges({ projectId, postId, review, playback, onSent }: Props) {
  const { t } = useTranslation();
  const now = useNow();
  const { data, mutate } = useSWR(draftsKey(projectId, postId), () => portalService.drafts(projectId, postId));
  const [text, setText] = useState("");
  const [atMoment, setAtMoment] = useState(true);
  const [adding, setAdding] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const moment = playback?.current && playback.playable.has(playback.current.media) ? playback.current : null;
  const drafts = data?.drafts ?? [];
  const expired = review.deadline ? new Date(review.deadline).getTime() <= now : false;

  if (!review.open || expired) return <ReviewBanner review={review} />;

  const add = async () => {
    const value = text.trim();
    if (!value || adding) return;
    setAdding(true);
    setError(null);
    try {
      const draft = await portalService.addDraft(
        projectId,
        postId,
        value,
        moment && atMoment ? { media: moment.media, at: moment.at } : undefined
      );
      await mutate((current) => ({ drafts: [...(current?.drafts ?? []), draft] }), { revalidate: false });
      setText("");
    } catch {
      setError(t("zil_portal.send_error"));
    } finally {
      setAdding(false);
    }
  };

  const send = async () => {
    setSending(true);
    setError(null);
    try {
      const sent = await portalService.sendChanges(projectId, postId);
      await mutate({ drafts: [] }, { revalidate: false });
      await onSent(sent.comments, sent.review);
      setConfirming(false);
    } catch {
      setError(t("zil_portal.send_error"));
      setConfirming(false);
    } finally {
      setSending(false);
    }
  };

  const leftAfter = review.left === null ? null : review.left - 1;
  return (
    <div className="space-y-3">
      <ReviewBanner review={review} />
      {drafts.length > 0 && (
        <div className="space-y-2">
          <h5 className="text-13 font-medium text-secondary">{t("zil_portal.drafts_title")}</h5>
          <ul className="space-y-2">
            {drafts.map((draft) => (
              <DraftRow
                key={draft.id}
                draft={draft}
                playback={playback}
                onSave={async (value) => {
                  const saved = await portalService.updateDraft(projectId, postId, draft.id, value);
                  await mutate(
                    (current) => ({ drafts: (current?.drafts ?? []).map((d) => (d.id === saved.id ? saved : d)) }),
                    { revalidate: false }
                  );
                }}
                onDelete={async () => {
                  await portalService.deleteDraft(projectId, postId, draft.id);
                  await mutate((current) => ({ drafts: (current?.drafts ?? []).filter((d) => d.id !== draft.id) }), {
                    revalidate: false,
                  });
                }}
              />
            ))}
          </ul>
        </div>
      )}
      <div className="space-y-2">
        <textarea
          value={text}
          onChange={(event) => setText(event.target.value)}
          // writing about a moment: the video stops there
          onFocus={() => playback?.pause()}
          placeholder={t("zil_portal.change_placeholder")}
          rows={3}
          maxLength={5000}
          className={TEXTAREA}
        />
        {moment && (
          <label className="flex cursor-pointer items-center gap-2 text-13 text-secondary">
            <Checkbox checked={atMoment} onChange={(event) => setAtMoment(event.target.checked)} />
            {t("zil_portal.comment_at", { time: clock(moment.at), name: moment.name })}
          </label>
        )}
        {error && <p className="text-13 text-danger-primary">{error}</p>}
        <div className="flex flex-wrap justify-end gap-2">
          <Button
            variant="secondary"
            onClick={add}
            disabled={!text.trim() || adding}
            className={cn(adding && "opacity-70")}
          >
            {t("zil_portal.add_change")}
          </Button>
          <Button variant="primary" onClick={() => setConfirming(true)} disabled={drafts.length === 0 || sending}>
            {t("zil_portal.send_changes", { count: drafts.length })}
          </Button>
        </div>
      </div>
      <AlertModalCore
        isOpen={confirming}
        variant="primary"
        title={t("zil_portal.confirm_title", { count: drafts.length })}
        content={
          leftAfter === null
            ? t("zil_portal.confirm_unlimited")
            : leftAfter <= 0
              ? t("zil_portal.confirm_last")
              : t("zil_portal.confirm_left", { left: leftAfter })
        }
        primaryButtonText={{ default: t("zil_portal.confirm_send"), loading: t("zil_portal.sending") }}
        secondaryButtonText={t("cancel")}
        isSubmitting={sending}
        handleClose={() => !sending && setConfirming(false)}
        handleSubmit={() => void send()}
      />
    </div>
  );
}
