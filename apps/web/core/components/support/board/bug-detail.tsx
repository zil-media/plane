/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import useSWR from "swr";
import { ArrowRight, ArrowUpRight, CheckCircle2, Lightbulb } from "lucide-react";
import { useTranslation } from "@plane/i18n";
import { Button } from "@plane/propel/button";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import { Loader, TextArea } from "@plane/ui";
import { cn, renderFormattedDate, renderFormattedTime } from "@plane/utils";
import type { TBugStatus } from "@/services/support.service";
import { supportErrorMessage, supportService } from "@/services/support.service";
import { PhaseChip, Tag } from "./item-row";
import { bugPhase, bugWasAnswered, bugWasDerived, bugWentToWorkspace } from "./phase";
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

/** The closing actions that still mean something for this status: no "resolve" on a resolved report. */
function closeActions(status: TBugStatus): ("resolve" | "dismiss" | "archive")[] {
  if (status === "archived") return [];
  if (status === "resolved" || status === "dismissed") return ["archive"];
  return ["resolve", "dismiss", "archive"];
}

/**
 * Where "see it in Workspace" goes. Workspace's tracking link is the reporter's own Seguimiento, which
 * only lists their reports: an admin looking at someone else's gets that report in Workspace's bug
 * admin page instead (an automatic one's link already points there).
 */
function workspaceLink(bug: { workspace_bug_url: string | null; workspace_bug_id: string | null }, asAdmin: boolean) {
  if (!asAdmin || !bug.workspace_bug_url || !bug.workspace_bug_id) return bug.workspace_bug_url;
  try {
    const url = new URL(bug.workspace_bug_url);
    if (url.pathname.startsWith("/dashboard/bug-reports")) return bug.workspace_bug_url;
    return `${url.origin}/dashboard/bug-reports?bugId=${encodeURIComponent(bug.workspace_bug_id)}`;
  } catch {
    return bug.workspace_bug_url;
  }
}

/** The routine's reason (routines.fire_bug_routine), said for the admin who pressed the button. */
function fixerNotStartedKey(reason: string) {
  if (reason === "disabled") return "helpdesk.admin.fixer_off";
  // A session is already running, or one just started: the reopened report is in its queue.
  if (reason === "session in flight" || reason === "cooldown") return "helpdesk.admin.fixer_busy";
  return "helpdesk.try_again";
}

export function SupportBugDetail({ bugId, isAdmin, currentUserId, onChanged, onOpenFeature }: Props) {
  const { t } = useTranslation();
  // Polled like the suggestion detail: the reporter watches the diagnosis move while the panel is open.
  const { data: bug, mutate } = useSWR(`SUPPORT_BUG:${bugId}`, () => supportService.bugReport(bugId), {
    refreshInterval: 20_000,
  });
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
  const workspaceUrl = bugWentToWorkspace(bug) ? workspaceLink(bug, isAdmin && !isOwner) : null;
  // a handover (suggestion or Workspace) reads as "what's next", not as "fixed"
  const handedOver = !!derivedFeatureId || bugWentToWorkspace(bug);
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
      const message = supportErrorMessage(error) ?? t("helpdesk.try_again");
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
          {/* What the reporter ticked: it promises it gets looked at first. Only a person ticks it (a CI
              incident is filed as bloqueante too). */}
          {bug.source === "manual" && bug.severity === "bloqueante" && <Tag>{t("helpdesk.reporter.urgent")}</Tag>}
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
      {/* The agent writes its message before the fix ships: "what we did" only once it's closed. */}
      {((bug.resolved_message && ["fixed", "resolved", "dismissed"].includes(bug.status)) || handedOver) && (
        <div
          className={cn(
            "flex flex-col gap-2 rounded-md border p-3",
            handedOver || answered ? "border-accent-strong bg-accent-subtle" : "border-success-strong bg-success-subtle"
          )}
        >
          <span
            className={cn(
              "flex items-center gap-2 text-caption-sm-medium",
              handedOver || answered ? "text-accent-primary" : "text-success-primary"
            )}
          >
            {handedOver ? <Lightbulb className="size-3.5" /> : <CheckCircle2 className="size-3.5" />}
            {t(
              handedOver
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
          {workspaceUrl && (
            <a
              href={workspaceUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1 self-start text-body-xs-medium text-accent-primary hover:underline"
            >
              {t("helpdesk.detail.see_in_workspace")}
              <ArrowUpRight className="size-3.5" />
            </a>
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

      {/* Fixed = the fix waits for the next publication (the countdown above says when): resending
          it then would only get "sale en la próxima publicación" back from the server. */}
      {isOwner && !bug.derived_feature_id && !bugWentToWorkspace(bug) && bug.status !== "fixed" && (
        <div className="flex flex-col gap-2 border-t border-subtle pt-3">
          <span className="text-caption-sm-medium text-tertiary">{t("helpdesk.detail.resend_hint")}</span>
          <TextArea
            value={comment}
            onChange={(event) => setComment(event.target.value)}
            maxLength={5000}
            className="min-h-20"
          />
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
            {/* Not while its fix waits for the publication: a new session would write it again (409). */}
            {bug.status !== "fixed" && (
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
                      message: result.fired ? undefined : t(fixerNotStartedKey(result.reason ?? "")),
                    });
                  })
                }
              >
                {t("helpdesk.admin.send_to_fixer")}
              </Button>
            )}
            {bug.blocked_at && (
              <Button
                variant="secondary"
                size="lg"
                onClick={() => void run(() => supportService.bulkBugAction("unblock", [bug.id]))}
              >
                {t("helpdesk.admin.unblock")}
              </Button>
            )}
            {closeActions(bug.status).map((action) => (
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
