/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import useSWR from "swr";
import { ArrowRight, CheckCircle2, Lightbulb } from "lucide-react";
import { useTranslation } from "@plane/i18n";
import { Button } from "@plane/propel/button";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import { Loader, TextArea } from "@plane/ui";
import { cn, renderFormattedDate, renderFormattedTime } from "@plane/utils";
import { supportService } from "@/services/support.service";
import { PhaseChip, Tag } from "./item-row";
import { bugPhase, bugWasAnswered, bugWasDerived } from "./phase";
import { PhaseTimeline } from "./phase-timeline";
import { SupportTimeline } from "./timeline";
import { computeBugTrack } from "./track";

type Props = {
  bugId: string;
  isAdmin: boolean;
  currentUserId?: string;
  onChanged: () => void;
  onOpenFeature: (id: string) => void;
};

export function SupportBugDetail({ bugId, isAdmin, currentUserId, onChanged, onOpenFeature }: Props) {
  const { t } = useTranslation();
  const { data: bug, mutate } = useSWR(`SUPPORT_BUG:${bugId}`, () => supportService.bugReport(bugId));
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);

  if (!bug)
    return (
      <Loader className="space-y-3 p-4">
        <Loader.Item height="24px" />
        <Loader.Item height="120px" />
      </Loader>
    );

  const derivedFeatureId = bugWasDerived(bug) ? bug.derived_feature_id : null;
  const answered = bugWasAnswered(bug);
  const isOwner = bug.reported_by?.id === currentUserId;
  // Without a generated title the raw text IS the heading, so it isn't repeated below.
  const heading = bug.display_title?.trim() || bug.description;

  const run = async (action: () => Promise<unknown>, success?: string) => {
    setBusy(true);
    try {
      await action();
      if (success) setToast({ type: TOAST_TYPE.SUCCESS, title: success });
      await mutate();
      onChanged();
    } catch (error) {
      const message = (error as { error?: string } | undefined)?.error ?? t("helpdesk.try_again");
      setToast({ type: TOAST_TYPE.ERROR, title: t("helpdesk.error_title"), message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col gap-4 p-4">
      <div className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <PhaseChip phase={bugPhase(bug)} />
          {bug.category && <Tag>{bug.category}</Tag>}
        </div>
        <h3 className="text-h6-medium break-words whitespace-pre-wrap text-primary">{heading}</h3>
        {bug.plain_summary && <p className="text-body-xs-regular text-secondary">{bug.plain_summary}</p>}
        <span className="text-caption-sm-regular text-tertiary">
          {t("helpdesk.board.reported_on", {
            date: `${renderFormattedDate(bug.created_at) ?? ""} ${renderFormattedTime(bug.created_at, "12-hour")}`,
          })}
        </span>
      </div>

      <PhaseTimeline track={computeBugTrack(bug)} />

      {/* Derived is NOT "how to do it": it can't be done yet, which is why a suggestion was opened. */}
      {(bug.resolved_message || derivedFeatureId) && (
        <div
          className={cn(
            "flex flex-col gap-2 rounded-md border p-3",
            derivedFeatureId || answered
              ? "border-accent-strong bg-accent-subtle"
              : "border-success-strong bg-success-subtle"
          )}
        >
          <span
            className={cn(
              "flex items-center gap-2 text-caption-sm-medium",
              derivedFeatureId || answered ? "text-accent-primary" : "text-success-primary"
            )}
          >
            {derivedFeatureId ? <Lightbulb className="size-3.5" /> : <CheckCircle2 className="size-3.5" />}
            {t(
              derivedFeatureId
                ? "helpdesk.detail.what_next"
                : answered
                  ? "helpdesk.detail.how_to"
                  : "helpdesk.detail.what_we_did"
            )}
          </span>
          {bug.resolved_message && (
            <p className="text-body-xs-regular whitespace-pre-wrap text-primary">{bug.resolved_message}</p>
          )}
          {derivedFeatureId && (
            <Button
              variant="secondary"
              size="lg"
              className="self-start"
              prependIcon={<ArrowRight />}
              onClick={() => onOpenFeature(derivedFeatureId)}
            >
              {t("helpdesk.detail.see_suggestion")}
            </Button>
          )}
        </div>
      )}

      {(heading !== bug.description || bug.url) && (
        <div className="flex flex-col gap-1 rounded-md border border-subtle p-3">
          <span className="text-caption-sm-medium text-primary">{t("helpdesk.detail.what_you_reported")}</span>
          {heading !== bug.description && (
            <p className="text-body-xs-regular break-words whitespace-pre-wrap text-secondary">{bug.description}</p>
          )}
          {bug.url && <span className="text-caption-sm-regular break-all text-tertiary">{bug.url}</span>}
        </div>
      )}

      {bug.attachments.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {bug.attachments.map((attachment) => (
            <a key={attachment.id} href={attachment.url} target="_blank" rel="noopener noreferrer">
              <img
                src={attachment.url}
                alt={attachment.name}
                className="h-20 rounded-sm border border-subtle object-cover"
              />
            </a>
          ))}
        </div>
      )}

      <SupportTimeline comments={bug.comments} />

      {isOwner && !bug.derived_feature_id && (
        <div className="flex flex-col gap-2 border-t border-subtle pt-3">
          <span className="text-caption-sm-medium text-tertiary">{t("helpdesk.detail.resend_hint")}</span>
          <TextArea value={comment} onChange={(event) => setComment(event.target.value)} className="min-h-20" />
          <Button
            variant="secondary"
            size="lg"
            className="self-end"
            loading={busy}
            disabled={!comment.trim()}
            onClick={() =>
              void run(async () => {
                await supportService.reopenBugReport(bug.id, comment.trim());
                setComment("");
              }, t("helpdesk.detail.resent"))
            }
          >
            {t("helpdesk.detail.resend")}
          </Button>
        </div>
      )}

      {isAdmin && (
        <div className="flex flex-col gap-2 border-t border-subtle pt-3">
          <span className="text-caption-sm-medium text-tertiary">
            {t("helpdesk.admin.actions")} · {bug.source} · {t("helpdesk.admin.occurrences", { count: bug.occurrences })}
          </span>
          {bug.blocked_reason && (
            <p className="rounded-md bg-layer-1 p-2 text-caption-sm-regular whitespace-pre-wrap text-secondary">
              {bug.blocked_reason}
            </p>
          )}
          <div className="flex flex-wrap gap-2">
            <Button
              variant="primary"
              size="lg"
              loading={busy}
              onClick={() =>
                void run(async () => {
                  const result = await supportService.sendToFixer(bug.id);
                  setToast({
                    type: result.fired ? TOAST_TYPE.SUCCESS : TOAST_TYPE.WARNING,
                    title: result.fired ? t("helpdesk.admin.fixer_sent") : t("helpdesk.admin.fixer_not_sent"),
                    message: result.reason,
                  });
                })
              }
            >
              {t("helpdesk.admin.send_to_fixer")}
            </Button>
            {bug.blocked_at && (
              <Button
                variant="secondary"
                size="lg"
                onClick={() => void run(() => supportService.bulkBugAction("unblock", [bug.id]))}
              >
                {t("helpdesk.admin.unblock")}
              </Button>
            )}
            {(["resolve", "dismiss", "archive"] as const).map((action) => (
              <Button
                key={action}
                variant="secondary"
                size="lg"
                onClick={() => void run(() => supportService.bulkBugAction(action, [bug.id]))}
              >
                {t(`helpdesk.admin.${action}`)}
              </Button>
            ))}
          </div>
          {bug.stack_trace && (
            <details className="text-caption-sm-regular text-tertiary">
              <summary className="cursor-pointer">{t("helpdesk.admin.technical_detail")}</summary>
              <pre className="mt-2 max-h-64 overflow-auto rounded-md bg-layer-1 p-2 text-[11px] whitespace-pre-wrap">
                {bug.stack_trace}
              </pre>
            </details>
          )}
        </div>
      )}
    </div>
  );
}
