/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useRef, useState } from "react";
import { CheckCircle2, ImagePlus, Lightbulb, Loader2, X } from "lucide-react";
import Link from "next/link";
import { mutate as globalMutate } from "swr";
import { useTranslation } from "@plane/i18n";
import { setToast } from "@plane/blocks/toast";
import { Button } from "@makeplane/propel/components/button";
import { Dialog, DialogContent, DialogTitle } from "@makeplane/propel/components/dialog";
import { Input } from "@makeplane/propel/components/input";
import { TextArea } from "@makeplane/propel/components/text-area";
import { EFileAssetType } from "@plane/types";
import { cn } from "@plane/utils";
import type { TFeaturePriority } from "@/services/support.service";
import { supportErrorMessage, supportService } from "@/services/support.service";
import { MAX_ATTACHMENTS, compressImage, uploadSupportImage } from "./attachments";
import { DraftReviewPanel, useDraftReview } from "./draft-review";

type Props = {
  isOpen: boolean;
  onClose: () => void;
  workspaceSlug: string;
};

const MIN_TITLE = 6;
const MIN_PROBLEM = 20;
/** The server's cap on problem / desired outcome. */
const MAX_TEXT = 10000;
const PRIORITIES: TFeaturePriority[] = ["baja", "media", "alta"];

type TAttachment = { key: string; name: string; assetId?: string; failed?: boolean };

export function FeatureSuggestModal(props: Props) {
  const { isOpen, onClose, workspaceSlug } = props;
  const { t } = useTranslation();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [step, setStep] = useState<1 | 2 | "sent">(1);
  const [title, setTitle] = useState("");
  const [problem, setProblem] = useState("");
  // Answers to the draft review, appended to the problem on send (see DraftReview).
  const [reviewAnswers, setReviewAnswers] = useState("");
  // Here and not inside the dialog, which unmounts its content on close: an accidental close keeps
  // the review's questions and answers along with the text.
  const review = useDraftReview({
    kind: "feature",
    title,
    text: problem,
    enabled: step !== "sent",
    paused: step !== 1 || !isOpen,
    onAnswersChange: setReviewAnswers,
  });
  const [desiredOutcome, setDesiredOutcome] = useState("");
  const [priority, setPriority] = useState<TFeaturePriority>("media");
  const [attachments, setAttachments] = useState<TAttachment[]>([]);
  const [submitting, setSubmitting] = useState(false);

  const titleOk = title.trim().length >= MIN_TITLE;
  const problemOk = problem.trim().length >= MIN_PROBLEM;
  const uploading = attachments.some((a) => !a.assetId && !a.failed);

  const reset = () => {
    setStep(1);
    setTitle("");
    setProblem("");
    setReviewAnswers("");
    review.reset();
    setDesiredOutcome("");
    setPriority("media");
    setAttachments([]);
  };

  // Closing by accident (outside click, Escape) keeps the draft, like the bug reporter. Only a sent
  // suggestion starts over, on the next open (that also covers closing while it was being sent).
  const handleClose = () => onClose();
  useEffect(() => {
    if (isOpen && step === "sent") reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only on open: reset after a send
  }, [isOpen]);

  const handleFiles = (files: FileList | null) => {
    const room = MAX_ATTACHMENTS - attachments.length;
    Array.from(files ?? [])
      .filter((file) => file.type.startsWith("image/"))
      .slice(0, Math.max(0, room))
      .forEach((file) => {
        const key = `${Date.now()}-${Math.random()}`;
        setAttachments((current) => [...current, { key, name: file.name }]);
        void compressImage(file, file.name)
          .then((compressed) =>
            uploadSupportImage(workspaceSlug, compressed, EFileAssetType.FEATURE_REQUEST_ATTACHMENT)
          )
          .then((assetId) => setAttachments((current) => current.map((a) => (a.key === key ? { ...a, assetId } : a))))
          .catch(() => setAttachments((current) => current.map((a) => (a.key === key ? { ...a, failed: true } : a))));
      });
  };

  const handleSubmit = async () => {
    setSubmitting(true);
    try {
      await supportService.createFeatureRequest({
        title: title.trim(),
        // The server caps the field at 10000: the review's answers go after the text, within it.
        problem: [problem.trim(), reviewAnswers.trim()].filter(Boolean).join("\n\n").slice(0, MAX_TEXT),
        desired_outcome: desiredOutcome.trim(),
        priority,
        source_url: window.location.pathname,
        attachment_ids: attachments.flatMap((a) => (a.assetId ? [a.assetId] : [])),
        workspace_slug: workspaceSlug,
      });
      setStep("sent");
      // "Ver el avance" lands on the board: it lists the new one now, not on its next 20s poll.
      void globalMutate("SUPPORT_FEATURES");
    } catch (error) {
      setToast({
        type: "error",
        title: t("helpdesk.suggest.error_title"),
        message: supportErrorMessage(error) ?? t("helpdesk.try_again"),
      });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog
      open={isOpen}
      onOpenChange={(open) => {
        if (!open) handleClose();
      }}
    >
      <DialogContent size="md">
        <div className="flex flex-col gap-4 p-5">
          <DialogTitle render={<div className="flex items-center gap-2 text-primary" />}>
            <Lightbulb className="size-5 text-accent-primary" />
            {t("helpdesk.suggest.title")}
          </DialogTitle>

          {step === "sent" && (
            <div className="flex flex-col items-start gap-4">
              <div className="flex items-start gap-2 text-body-sm-regular text-secondary">
                <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-success-primary" />
                {t("helpdesk.suggest.sent")}
              </div>
              <div className="flex gap-2 self-end">
                <Button
                  stretch="auto"
                  variant="secondary"
                  size="lg"
                  onClick={handleClose}
                  label={t("helpdesk.close")}
                />
                <Link href={`/${workspaceSlug}/support`} onClick={handleClose}>
                  <Button stretch="auto" variant="primary" size="lg" label={t("helpdesk.reporter.view_tracking")} />
                </Link>
              </div>
            </div>
          )}

          {step === 1 && (
            <>
              <p className="text-body-xs-regular text-tertiary">{t("helpdesk.suggest.intro")}</p>
              <label className="flex flex-col gap-1.5">
                <span className="text-body-xs-medium text-secondary">{t("helpdesk.suggest.what_label")}</span>
                <Input
                  size="md"
                  value={title}
                  onChange={(event) => setTitle(event.target.value)}
                  placeholder={t("helpdesk.suggest.what_placeholder")}
                  maxLength={200}
                />
              </label>
              <label className="flex flex-col gap-1.5">
                <span className="text-body-xs-medium text-secondary">{t("helpdesk.suggest.why_label")}</span>
                <TextArea
                  surface="field"
                  size="md"
                  rows={5}
                  value={problem}
                  onChange={(event) => setProblem(event.target.value)}
                  placeholder={t("helpdesk.suggest.why_placeholder")}
                  maxLength={MAX_TEXT}
                />
                <span className={cn("text-caption-sm-regular", problemOk ? "text-success-primary" : "text-tertiary")}>
                  {t("helpdesk.suggest.why_hint")}
                </span>
              </label>
            </>
          )}

          {step === 1 && <DraftReviewPanel review={review} />}

          {step === 1 && (
            <div className="flex justify-end gap-2">
              <Button stretch="auto" variant="secondary" size="lg" onClick={handleClose} label={t("helpdesk.cancel")} />
              <Button
                stretch="auto"
                variant="primary"
                size="lg"
                disabled={!titleOk || !problemOk}
                onClick={() => setStep(2)}
                label={t("helpdesk.suggest.next")}
              />
            </div>
          )}

          {step === 2 && (
            <>
              <label className="flex flex-col gap-1.5">
                <span className="text-body-xs-medium text-secondary">{t("helpdesk.suggest.how_label")}</span>
                <TextArea
                  surface="field"
                  size="md"
                  rows={4}
                  value={desiredOutcome}
                  onChange={(event) => setDesiredOutcome(event.target.value)}
                  placeholder={t("helpdesk.suggest.how_placeholder")}
                  maxLength={MAX_TEXT}
                />
              </label>
              <div className="flex flex-col gap-1.5">
                <span className="text-body-xs-medium text-secondary">{t("helpdesk.suggest.priority_label")}</span>
                <div className="flex gap-2">
                  {PRIORITIES.map((value) => (
                    <Button
                      stretch="auto"
                      key={value}
                      variant={priority === value ? "primary" : "secondary"}
                      size="lg"
                      onClick={() => setPriority(value)}
                      label={t(`helpdesk.priority.${value}`)}
                    />
                  ))}
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                {attachments.map((attachment) => (
                  <span
                    key={attachment.key}
                    className={cn(
                      "flex items-center gap-1 rounded-sm border border-subtle px-2 py-1 text-caption-sm-regular",
                      attachment.failed ? "text-danger-primary" : "text-secondary"
                    )}
                  >
                    {!attachment.assetId && !attachment.failed && <Loader2 className="size-3 animate-spin" />}
                    <span className="max-w-32 truncate">{attachment.name}</span>
                    <button
                      type="button"
                      aria-label={t("helpdesk.reporter.remove_image")}
                      onClick={() => setAttachments((current) => current.filter((a) => a.key !== attachment.key))}
                    >
                      <X className="size-3" />
                    </button>
                  </span>
                ))}
                {attachments.length < MAX_ATTACHMENTS && (
                  <Button
                    stretch="auto"
                    variant="ghost"
                    size="lg"
                    icon={<ImagePlus />}
                    onClick={() => fileInputRef.current?.click()}
                    label={t("helpdesk.suggest.add_images")}
                  />
                )}
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="image/*"
                  multiple
                  className="hidden"
                  onChange={(event) => {
                    handleFiles(event.target.files);
                    event.target.value = "";
                  }}
                />
              </div>
              <div className="flex justify-between gap-2">
                <Button
                  stretch="auto"
                  variant="ghost"
                  size="lg"
                  onClick={() => setStep(1)}
                  label={t("helpdesk.suggest.back")}
                />
                <Button
                  stretch="auto"
                  variant="primary"
                  size="lg"
                  loading={submitting}
                  disabled={uploading}
                  onClick={() => void handleSubmit()}
                  label={t("helpdesk.suggest.submit")}
                />
              </div>
            </>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
