/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import useSWR, { mutate as globalMutate } from "swr";
import { useTranslation } from "@plane/i18n";
import { Button } from "@plane/propel/button";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import { Input, Loader, TextArea, ToggleSwitch } from "@plane/ui";
import { renderFormattedDate } from "@plane/utils";
import { SUPPORT_FEATURE_FLAGS_KEY } from "@/hooks/use-feature-flag";
import type { TFeatureDecision, TFeatureRequestDetail } from "@/services/support.service";
import { supportErrorMessage, supportService } from "@/services/support.service";
import { AgentConsult } from "./agent-consult";
import { PhaseChip, Tag } from "./item-row";
import { featurePhase } from "./phase";
import { PhaseTimeline } from "./phase-timeline";
import { SupportTimeline } from "./timeline";
import { computeFeatureTrack } from "./track";

type Props = {
  featureId: string;
  isAdmin: boolean;
  currentUserId?: string;
  enabledFlags: string[];
  onChanged: () => void;
};

/** The agent re-runs the impact analysis on its own up to this many times. */
const AUTO_SPEC_RUNS = 3;
/** Same pace as the board list: without it the panel kept offering decisions someone else already took. */
const REFRESH_MS = 20_000;

/** Why an approved feature didn't start building (request_build's reasons), in the person's words. */
function buildNotStartedKey(reason: string) {
  if (reason === "disabled") return "helpdesk.detail.agent_off";
  if (reason === "another build in flight") return "helpdesk.admin.build_busy";
  if (reason === "build run limit") return "helpdesk.admin.build_limit";
  if (reason.startsWith("tope semanal")) return "helpdesk.admin.build_cap";
  return "helpdesk.try_again";
}

/** What the primary action means in each state; `null` when an admin has nothing to decide. */
type TPrimary = { decision: TFeatureDecision; labelKey: string; needsFlag: boolean } | null;

/**
 * What an admin can do TODAY, in this state. Only what the server accepts from it
 * (FeatureRequestDecisionEndpoint.ALLOWED_FROM): offering the rest just ends in a 409.
 */
function adminOptions(feature: TFeatureRequestDetail) {
  const blocked = feature.build_blocked;
  // An approval older than the current spec approved a different analysis (approve, pause, redo the
  // analysis): resuming that one would build what nobody approved. ISO strings of the same zone compare.
  const approvedAt = feature.approval?.at;
  const specAt = feature.spec?.generated_at;
  const wasApproved = !!approvedAt && (!specAt || approvedAt >= specAt);
  let primary: TPrimary = null;
  const secondary: { decision: TFeatureDecision; labelKey: string }[] = [];
  let canReject = false;

  switch (feature.status) {
    case "spec_ready":
      primary = { decision: "approve", labelKey: "helpdesk.admin.approve", needsFlag: true };
      secondary.push({ decision: "hold", labelKey: "helpdesk.admin.hold" });
      canReject = true;
      break;
    case "submitted":
    case "needs_info":
      secondary.push({ decision: "hold", labelKey: "helpdesk.admin.hold" });
      canReject = true;
      break;
    case "approved":
      primary = { decision: "rebuild", labelKey: "helpdesk.admin.start_now", needsFlag: false };
      secondary.push({ decision: "hold", labelKey: "helpdesk.admin.hold" });
      canReject = true;
      break;
    case "building":
      // A stuck build stays in "building" with build.blocked_at set (agent build-status "blocked"):
      // it waits for a person, so retrying is THE action. A live build can still be restarted.
      if (blocked) primary = { decision: "rebuild", labelKey: "helpdesk.admin.retry_build", needsFlag: false };
      else secondary.push({ decision: "rebuild", labelKey: "helpdesk.admin.rebuild" });
      secondary.push({ decision: "hold", labelKey: "helpdesk.admin.hold" });
      canReject = true;
      break;
    case "in_review":
      // A PR closed without merging leaves it here: pausing or rejecting is the way out.
      secondary.push({ decision: "rebuild", labelKey: "helpdesk.admin.rebuild" });
      secondary.push({ decision: "hold", labelKey: "helpdesk.admin.hold" });
      canReject = true;
      break;
    case "queued":
      // Dropped from the batch, or not wanted after all: rejecting keeps merged code dark.
      canReject = true;
      break;
    case "on_hold":
      // Paused after it was approved: resuming is building again. Paused with a spec ready but
      // never approved: resuming is approving it. Paused before any spec: redo the analysis.
      if (wasApproved) primary = { decision: "rebuild", labelKey: "helpdesk.admin.resume_build", needsFlag: false };
      else if (feature.spec?.generated_at)
        primary = { decision: "approve", labelKey: "helpdesk.admin.approve", needsFlag: true };
      canReject = true;
      break;
    default:
      break;
  }
  return { primary, secondary, canReject };
}

/** The sentence that says who has the ball now, for whoever is looking. */
function nextStepKey(feature: TFeatureRequestDetail, isAdmin: boolean, isRequester: boolean, flagOn: boolean) {
  switch (feature.status) {
    case "needs_info":
      if (feature.answered) return isAdmin ? "helpdesk.next.answered_you" : "helpdesk.next.answered";
      return isRequester ? "helpdesk.next.needs_info_you" : "helpdesk.next.needs_info";
    case "spec_ready":
      return isAdmin ? "helpdesk.next.spec_ready_you" : "helpdesk.next.spec_ready";
    case "approved":
      return "helpdesk.next.approved";
    case "building":
      if (!feature.build_blocked) return "helpdesk.next.building";
      return isAdmin ? "helpdesk.next.stuck_you" : "helpdesk.next.stuck";
    case "in_review":
      return "helpdesk.next.in_review";
    case "queued":
      return "helpdesk.next.queued";
    case "merged":
      return flagOn ? "helpdesk.next.merged_on" : "helpdesk.next.merged_off";
    case "on_hold":
      return "helpdesk.next.on_hold";
    case "rejected":
      return "helpdesk.next.rejected";
    default:
      return "helpdesk.next.analyzing";
  }
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-caption-sm-medium text-tertiary">{label}</span>
      <div className="text-body-xs-regular break-words whitespace-pre-wrap text-secondary">{children}</div>
    </div>
  );
}

export function SupportFeatureDetail({ featureId, isAdmin, currentUserId, enabledFlags, onChanged }: Props) {
  const { t } = useTranslation();
  const { data: feature, mutate } = useSWR(
    `SUPPORT_FEATURE:${featureId}`,
    () => supportService.featureRequest(featureId),
    { refreshInterval: REFRESH_MS }
  );
  const [comment, setComment] = useState("");
  const [notes, setNotes] = useState("");
  const [flagKey, setFlagKey] = useState<string | null>(null);
  const [rejecting, setRejecting] = useState(false);
  const [busy, setBusy] = useState(false);
  // The status can move under an open reject form (refresh, another admin): start over.
  const status = feature?.status;
  useEffect(() => setRejecting(false), [status]);

  if (!feature)
    return (
      <Loader className="space-y-3 p-4">
        <Loader.Item height="24px" />
        <Loader.Item height="120px" />
      </Loader>
    );

  const spec = feature.spec ?? {};
  const isRequester = feature.requested_by?.id === currentUserId;
  const flagOn = !!feature.flag_key && enabledFlags.includes(feature.flag_key);
  const consult = feature.status === "needs_info" && isRequester;
  // The consult card IS the answer box: a second textarea under it would split the answer.
  const canComment = (isRequester || isAdmin) && !consult && !["merged", "rejected"].includes(feature.status);
  // Redoing the analysis resumes a paused request, and pausing is an admin's call: the requester
  // can't undo it from here.
  const canRespec =
    (isAdmin && ["submitted", "spec_ready", "needs_info", "on_hold"].includes(feature.status)) ||
    (isRequester && ["submitted", "spec_ready", "needs_info"].includes(feature.status));
  const specRuns = feature.spec_runs ?? 0;
  const { primary, secondary, canReject } = isAdmin
    ? adminOptions(feature)
    : { primary: null, secondary: [], canReject: false };
  const effectiveFlagKey = (flagKey ?? feature.flag_key).trim();

  const run = async (action: () => Promise<unknown>, success?: string) => {
    setBusy(true);
    try {
      await action();
      if (success) setToast({ type: TOAST_TYPE.SUCCESS, title: success });
      await mutate();
      onChanged();
    } catch (error) {
      setToast({
        type: TOAST_TYPE.ERROR,
        title: t("helpdesk.error_title"),
        message: supportErrorMessage(error) ?? t("helpdesk.try_again"),
      });
      // A 409 usually means someone else moved it first: show where it is now.
      await mutate();
    } finally {
      setBusy(false);
    }
  };

  const decide = (decision: TFeatureDecision, data: { notes?: string; flag_key?: string } = {}) =>
    run(async () => {
      const result = await supportService.decideFeatureRequest(feature.id, decision, data);
      setNotes("");
      setRejecting(false);
      if (result.build && !result.build.fired)
        setToast({
          type: TOAST_TYPE.WARNING,
          title: t("helpdesk.admin.build_not_started"),
          message: t(buildNotStartedKey(result.build.reason)),
        });
    });

  const respec = () =>
    run(async () => {
      const result = await supportService.respecFeatureRequest(feature.id);
      setToast(
        result.queued
          ? { type: TOAST_TYPE.SUCCESS, title: t("helpdesk.detail.respec_done") }
          : {
              type: TOAST_TYPE.WARNING,
              title: t("helpdesk.detail.respec_not_done"),
              message: t(result.reason === "disabled" ? "helpdesk.detail.agent_off" : "helpdesk.try_again"),
            }
      );
    });

  const hasActions = !!primary || secondary.length > 0 || canReject || canRespec;

  return (
    <div className="flex flex-col gap-4 p-4">
      <div className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <PhaseChip phase={featurePhase(feature)} />
          {feature.category && <Tag>{feature.category}</Tag>}
          {feature.priority && (
            <Tag>
              {t("helpdesk.detail.priority")}: {t(`helpdesk.priority.${feature.priority}`)}
            </Tag>
          )}
        </div>
        <h3 className="text-h6-medium text-primary">{feature.display_title || feature.title}</h3>
        {feature.plain_summary && <p className="text-body-xs-regular text-secondary">{feature.plain_summary}</p>}
        <span className="text-caption-sm-regular text-tertiary">
          {feature.requested_by?.display_name} · {renderFormattedDate(feature.created_at)}
        </span>
      </div>

      {consult && (
        // Keyed on the agent's questions and the server's `answered`: a new question (asked while the
        // panel stayed open) brings the answer box back instead of the old "already answered" state.
        <AgentConsult
          key={`${(feature.comments ?? []).filter((entry) => entry.role === "agent").length}-${feature.answered}`}
          feature={feature}
          onAnswered={() => void mutate().then(onChanged)}
        />
      )}

      {/* ── What's next: who has the ball, and what an admin can do about it right now ── */}
      <div className="flex flex-col gap-3 rounded-md border border-subtle p-3">
        <Field label={t("helpdesk.detail.what_next")}>{t(nextStepKey(feature, isAdmin, isRequester, flagOn))}</Field>

        {primary?.needsFlag && (
          <label className="flex flex-col gap-1">
            <span className="text-caption-sm-regular text-tertiary">{t("helpdesk.admin.flag_key")}</span>
            <Input value={flagKey ?? feature.flag_key} onChange={(event) => setFlagKey(event.target.value)} />
          </label>
        )}

        {rejecting && canReject && (
          <TextArea
            value={notes}
            onChange={(event) => setNotes(event.target.value)}
            placeholder={t("helpdesk.admin.reject_reason_placeholder")}
            className="min-h-16"
          />
        )}

        {hasActions && (
          <div className="flex flex-wrap gap-2">
            {rejecting && canReject ? (
              <>
                <Button
                  variant="error-fill"
                  size="lg"
                  loading={busy}
                  disabled={!notes.trim()}
                  onClick={() => void decide("reject", { notes: notes.trim() })}
                >
                  {t("helpdesk.admin.reject_confirm")}
                </Button>
                <Button variant="secondary" size="lg" onClick={() => setRejecting(false)}>
                  {t("helpdesk.cancel")}
                </Button>
              </>
            ) : (
              <>
                {primary && (
                  <Button
                    variant="primary"
                    size="lg"
                    loading={busy}
                    disabled={primary.needsFlag && !effectiveFlagKey}
                    onClick={() =>
                      void decide(primary.decision, primary.needsFlag ? { flag_key: effectiveFlagKey } : {})
                    }
                  >
                    {t(primary.labelKey)}
                  </Button>
                )}
                {secondary.map((option) => (
                  <Button
                    key={option.decision}
                    variant="secondary"
                    size="lg"
                    loading={busy}
                    onClick={() => void decide(option.decision)}
                  >
                    {t(option.labelKey)}
                  </Button>
                ))}
                {canRespec && (
                  <Button variant="secondary" size="lg" loading={busy} onClick={() => void respec()}>
                    {specRuns < AUTO_SPEC_RUNS
                      ? t("helpdesk.detail.respec", { runs: String(specRuns), max: String(AUTO_SPEC_RUNS) })
                      : t("helpdesk.detail.respec_again")}
                  </Button>
                )}
                {canReject && (
                  <Button variant="error-outline" size="lg" onClick={() => setRejecting(true)}>
                    {t("helpdesk.admin.reject")}
                  </Button>
                )}
              </>
            )}
          </div>
        )}

        {isAdmin && feature.flag_key && ["merged", "queued", "in_review"].includes(feature.status) && (
          <div className="flex items-center justify-between gap-3 rounded-md bg-layer-1 px-3 py-2">
            <span className="flex flex-col">
              <span className="text-body-xs-medium text-primary">{t("helpdesk.admin.flag_toggle")}</span>
              <span className="text-caption-sm-regular text-tertiary">{feature.flag_key}</span>
            </span>
            <ToggleSwitch
              value={flagOn}
              size="sm"
              label={t("helpdesk.admin.flag_toggle")}
              onChange={() =>
                void run(async () => {
                  await supportService.setFeatureFlag(feature.id, !flagOn);
                  await globalMutate(SUPPORT_FEATURE_FLAGS_KEY);
                })
              }
            />
          </div>
        )}
        {isAdmin && feature.pr_url && (
          <a
            href={feature.pr_url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-caption-sm-regular text-link-primary hover:underline"
          >
            {t("helpdesk.admin.open_pr")}
          </a>
        )}
      </div>

      <PhaseTimeline track={computeFeatureTrack(feature)} />

      {/* The note explains why a build stopped or was paused; once it moves on, it would read as stale. */}
      {feature.build?.last_note && ["building", "approved", "on_hold"].includes(feature.status) && (
        <div className="rounded-md bg-layer-1 p-3 text-body-xs-regular whitespace-pre-wrap text-primary">
          {feature.build.last_note}
        </div>
      )}

      <Field label={t("helpdesk.detail.request")}>
        <strong className="text-primary">{feature.title}</strong>
        {"\n"}
        {feature.problem}
      </Field>
      {feature.desired_outcome && <Field label={t("helpdesk.suggest.how_label")}>{feature.desired_outcome}</Field>}

      {feature.attachments.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {feature.attachments.map((attachment) => (
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

      {spec.summary && (
        <div className="flex flex-col gap-3 rounded-md border border-subtle p-3">
          <Field label={t("helpdesk.detail.analysis")}>{spec.summary}</Field>
          {isAdmin && spec.approach && <Field label={t("helpdesk.detail.approach")}>{spec.approach}</Field>}
          <div className="flex flex-wrap gap-4 text-caption-sm-regular text-secondary">
            {spec.blast_radius && (
              <span>
                {t("helpdesk.detail.impact")}: {t(`helpdesk.impact.${spec.blast_radius}`)}
              </span>
            )}
            {spec.effort && (
              <span>
                {t("helpdesk.detail.effort")}: {spec.effort}
              </span>
            )}
          </div>
          {isAdmin && spec.risks && spec.risks.length > 0 && (
            <Field label={t("helpdesk.detail.risks")}>{spec.risks.map((risk) => `• ${risk}`).join("\n")}</Field>
          )}
        </div>
      )}

      <SupportTimeline comments={feature.comments} />

      {canComment && (
        <div className="flex flex-col gap-2 border-t border-subtle pt-3">
          <span className="text-caption-sm-medium text-tertiary">{t("helpdesk.detail.comment")}</span>
          <TextArea value={comment} onChange={(event) => setComment(event.target.value)} className="min-h-20" />
          <Button
            variant="secondary"
            size="lg"
            className="self-end"
            loading={busy}
            disabled={!comment.trim()}
            onClick={() =>
              void run(async () => {
                await supportService.commentFeatureRequest(feature.id, comment.trim());
                setComment("");
              })
            }
          >
            {t("helpdesk.detail.send")}
          </Button>
        </div>
      )}
    </div>
  );
}
