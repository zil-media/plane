/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import type { ReactNode } from "react";
import useSWR, { mutate as globalMutate } from "swr";
import { useTranslation } from "@plane/i18n";
import { Button } from "@plane/propel/button";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import { Input, Loader, TextArea, ToggleSwitch } from "@plane/ui";
import { cn, renderFormattedDate } from "@plane/utils";
import { SUPPORT_FEATURE_FLAGS_KEY } from "@/hooks/use-feature-flag";
import type { TFeatureDecision } from "@/services/support.service";
import { supportService } from "@/services/support.service";
import { TONE_DOT, featurePhase, nextDeployWindow } from "./phase";
import { SupportTimeline } from "./timeline";

type Props = {
  featureId: string;
  isAdmin: boolean;
  currentUserId?: string;
  enabledFlags: string[];
  onChanged: () => void;
};

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
  const { data: feature, mutate } = useSWR(`SUPPORT_FEATURE:${featureId}`, () =>
    supportService.featureRequest(featureId)
  );
  const [comment, setComment] = useState("");
  const [notes, setNotes] = useState("");
  const [flagKey, setFlagKey] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (!feature)
    return (
      <Loader className="space-y-3 p-4">
        <Loader.Item height="24px" />
        <Loader.Item height="120px" />
      </Loader>
    );

  const phase = featurePhase(feature);
  const spec = feature.spec ?? {};
  const isRequester = feature.requested_by?.id === currentUserId;
  const canComment = isRequester || isAdmin;
  const flagOn = !!feature.flag_key && enabledFlags.includes(feature.flag_key);

  const run = async (action: () => Promise<unknown>) => {
    setBusy(true);
    try {
      await action();
      await mutate();
      onChanged();
    } catch (error) {
      const message = (error as { error?: string } | undefined)?.error ?? t("helpdesk.try_again");
      setToast({ type: TOAST_TYPE.ERROR, title: t("helpdesk.error_title"), message });
    } finally {
      setBusy(false);
    }
  };

  const decide = (decision: TFeatureDecision) =>
    run(() =>
      supportService.decideFeatureRequest(feature.id, decision, {
        notes: notes.trim(),
        ...(flagKey ? { flag_key: flagKey } : {}),
      })
    );

  return (
    <div className="flex flex-col gap-4 p-4">
      <div className="flex flex-col gap-1.5">
        <span className="flex items-center gap-1.5 text-caption-sm-regular text-secondary">
          <span className={cn("size-2 rounded-full", TONE_DOT[phase.tone])} />
          {t(phase.labelKey)}
          {feature.status === "queued" &&
            ` · ${t("helpdesk.detail.next_window", { date: renderFormattedDate(nextDeployWindow()) ?? "" })}`}
        </span>
        <h3 className="text-h6-medium text-primary">{feature.display_title || feature.title}</h3>
        {feature.plain_summary && <p className="text-body-xs-regular text-secondary">{feature.plain_summary}</p>}
      </div>

      {feature.build?.last_note && (
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

      <SupportTimeline progress={feature.build?.progress} comments={feature.comments} />

      {canComment && !["merged", "rejected"].includes(feature.status) && (
        <div className="flex flex-col gap-2 border-t border-subtle pt-3">
          <span className="text-caption-sm-medium text-tertiary">
            {feature.status === "needs_info" && isRequester
              ? t("helpdesk.detail.answer_hint")
              : t("helpdesk.detail.comment")}
          </span>
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

      {isAdmin && (
        <div className="flex flex-col gap-2 border-t border-subtle pt-3">
          <span className="text-caption-sm-medium text-tertiary">{t("helpdesk.admin.decision")}</span>
          {feature.status !== "merged" && (
            <>
              <label className="flex flex-col gap-1">
                <span className="text-caption-sm-regular text-tertiary">{t("helpdesk.admin.flag_key")}</span>
                <Input
                  value={flagKey ?? feature.flag_key}
                  onChange={(event) => setFlagKey(event.target.value)}
                  placeholder="miFeature"
                />
              </label>
              <TextArea
                value={notes}
                onChange={(event) => setNotes(event.target.value)}
                placeholder={t("helpdesk.admin.notes_placeholder")}
                className="min-h-16"
              />
              <div className="flex flex-wrap gap-2">
                {(["approve", "rebuild", "hold", "reject"] as const).map((decision) => (
                  <Button
                    key={decision}
                    variant={decision === "approve" ? "primary" : decision === "reject" ? "error-outline" : "secondary"}
                    size="lg"
                    loading={busy}
                    onClick={() => void decide(decision)}
                  >
                    {t(`helpdesk.admin.${decision}`)}
                  </Button>
                ))}
              </div>
            </>
          )}
          {feature.flag_key && ["merged", "queued", "in_review"].includes(feature.status) && (
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
          {feature.pr_url && (
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
      )}
    </div>
  );
}
