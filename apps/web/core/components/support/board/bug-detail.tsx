/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import useSWR from "swr";
import { useTranslation } from "@plane/i18n";
import { Button } from "@plane/propel/button";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import { Loader, TextArea } from "@plane/ui";
import { cn, renderFormattedDate } from "@plane/utils";
import { supportService } from "@/services/support.service";
import { TONE_DOT, bugPhase, nextDeployWindow } from "./phase";
import { SupportTimeline } from "./timeline";

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

  const phase = bugPhase(bug);
  const derivedFeatureId = bug.derived_feature_id;
  const isOwner = bug.reported_by?.id === currentUserId;

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
      <div className="flex flex-col gap-1.5">
        <span className="flex items-center gap-1.5 text-caption-sm-regular text-secondary">
          <span className={cn("size-2 rounded-full", TONE_DOT[phase.tone])} />
          {t(phase.labelKey)}
          {bug.status === "fixed" &&
            ` · ${t("helpdesk.detail.next_window", { date: renderFormattedDate(nextDeployWindow()) ?? "" })}`}
        </span>
        <h3 className="text-h6-medium text-primary">{bug.display_title || t("helpdesk.detail.bug_report")}</h3>
        {bug.plain_summary && <p className="text-body-xs-regular text-secondary">{bug.plain_summary}</p>}
      </div>

      {bug.resolved_message && (
        <div className="rounded-md bg-layer-1 p-3 text-body-xs-regular whitespace-pre-wrap text-primary">
          <span className="mb-1 block text-caption-sm-medium text-tertiary">{t("helpdesk.detail.our_answer")}</span>
          {bug.resolved_message}
        </div>
      )}

      {derivedFeatureId && (
        <Button variant="link" size="lg" className="self-start" onClick={() => onOpenFeature(derivedFeatureId)}>
          {t("helpdesk.detail.see_suggestion")}
        </Button>
      )}

      <div className="flex flex-col gap-1">
        <span className="text-caption-sm-medium text-tertiary">{t("helpdesk.detail.what_you_reported")}</span>
        <p className="text-body-xs-regular break-words whitespace-pre-wrap text-secondary">{bug.description}</p>
        <span className="text-caption-sm-regular text-tertiary">
          {renderFormattedDate(bug.created_at)} {bug.url && `· ${bug.url}`}
        </span>
      </div>

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

      <SupportTimeline progress={bug.progress} comments={bug.comments} />

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
