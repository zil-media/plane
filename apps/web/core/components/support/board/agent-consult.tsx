/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { CheckCircle2, MessageCircleQuestion } from "lucide-react";
import { useTranslation } from "@plane/i18n";
import { Button } from "@plane/propel/button";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import { TextArea } from "@plane/ui";
import { cn } from "@plane/utils";
import type { TFeatureRequestDetail, TRespecResult, TSupportComment } from "@/services/support.service";
import { supportService } from "@/services/support.service";

type Props = {
  feature: TFeatureRequestDetail;
  onAnswered: () => void;
};

/**
 * The agent's open questions. needs_info stores the exact list in spec.open_questions; the last
 * agent comment ("- question" lines) is the fallback for features asked before that.
 */
export function agentQuestions(feature: TFeatureRequestDetail): string[] {
  if (feature.spec?.open_questions?.length) return feature.spec.open_questions;
  let asked: TSupportComment | undefined;
  for (const comment of feature.comments ?? []) if (comment.role === "agent") asked = comment;
  const lines = (asked?.text ?? "")
    .split("\n")
    .map((line) => line.replace(/^\s*[-•]\s*/, "").trim())
    .filter(Boolean);
  return lines;
}

/**
 * The needs-info loop, made prominent: what the agent asked and the box to answer it. Before
 * this the questions sat in the comment thread and the answer box looked like any comment.
 *
 * The server already sends the request back to analysis when the person who asked answers; this
 * only shows whether that actually happened. The comment always lands, but the analysis may not
 * restart (feature agent off), and announcing "restarted" then would say the opposite of the truth.
 */
export function AgentConsult({ feature, onAnswered }: Props) {
  const { t } = useTranslation();
  const [answer, setAnswer] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<TRespecResult | null>(null);
  const questions = agentQuestions(feature);

  const send = async () => {
    setBusy(true);
    try {
      const response = await supportService.commentFeatureRequest(feature.id, answer.trim());
      const respec = response.respec ?? { queued: false, reason: "" };
      setResult(respec);
      setAnswer("");
      // Once relaunched the feature leaves needs_info and this card unmounts on the refetch: the
      // toast is what's left to say it worked.
      if (respec.queued) setToast({ type: TOAST_TYPE.SUCCESS, title: t("helpdesk.consult.relaunched") });
      onAnswered();
    } catch {
      setToast({ type: TOAST_TYPE.ERROR, title: t("helpdesk.error_title"), message: t("helpdesk.try_again") });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className={cn(
        "flex flex-col gap-2 rounded-md border p-3",
        result && !result.queued ? "border-warning-strong bg-warning-subtle" : "border-accent-strong bg-accent-subtle"
      )}
    >
      <span className="flex items-center gap-2 text-body-xs-medium text-accent-primary">
        <MessageCircleQuestion className="size-4 shrink-0" />
        {t("helpdesk.consult.title")}
      </span>
      {questions.length > 0 && (
        <ul className="flex flex-col gap-1">
          {questions.map((question) => (
            <li key={question} className="flex gap-2 text-body-xs-regular break-words text-primary">
              <span className="text-accent-primary">•</span>
              <span className="min-w-0">{question}</span>
            </li>
          ))}
        </ul>
      )}
      {result ? (
        <span
          className={cn(
            "flex items-start gap-2 text-body-xs-regular",
            result.queued ? "text-success-primary" : "text-warning-primary"
          )}
        >
          <CheckCircle2 className="mt-0.5 size-3.5 shrink-0" />
          {result.queued
            ? t("helpdesk.consult.relaunched")
            : t(
                result.reason === "disabled" ? "helpdesk.consult.not_relaunched_off" : "helpdesk.consult.not_relaunched"
              )}
        </span>
      ) : (
        <>
          <span className="text-caption-sm-regular text-tertiary">{t("helpdesk.consult.intro")}</span>
          <TextArea
            value={answer}
            onChange={(event) => setAnswer(event.target.value)}
            placeholder={t("helpdesk.consult.placeholder")}
            className="min-h-20 bg-surface-1"
          />
          <Button
            variant="primary"
            size="lg"
            className="self-end"
            loading={busy}
            disabled={!answer.trim()}
            onClick={() => void send()}
          >
            {t("helpdesk.consult.send")}
          </Button>
        </>
      )}
    </div>
  );
}
