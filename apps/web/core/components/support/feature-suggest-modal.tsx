/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useRef, useState } from "react";
import { CheckCircle2, ImagePlus, Lightbulb, Loader2, X } from "lucide-react";
import Link from "next/link";
import { useTranslation } from "@plane/i18n";
import { Button } from "@plane/propel/button";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import { EFileAssetType } from "@plane/types";
import { EModalPosition, EModalWidth, Input, ModalCore, TextArea } from "@plane/ui";
import { cn } from "@plane/utils";
import type { TFeaturePriority } from "@/services/support.service";
import { supportService } from "@/services/support.service";
import { MAX_ATTACHMENTS, compressImage, uploadSupportImage } from "./attachments";

type Props = {
  isOpen: boolean;
  onClose: () => void;
  workspaceSlug: string;
};

const MIN_TITLE = 6;
const MIN_PROBLEM = 20;
const PRIORITIES: TFeaturePriority[] = ["baja", "media", "alta"];

type TAttachment = { key: string; name: string; assetId?: string; failed?: boolean };

export function FeatureSuggestModal(props: Props) {
  const { isOpen, onClose, workspaceSlug } = props;
  const { t } = useTranslation();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [step, setStep] = useState<1 | 2 | "sent">(1);
  const [title, setTitle] = useState("");
  const [problem, setProblem] = useState("");
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
    setDesiredOutcome("");
    setPriority("media");
    setAttachments([]);
  };

  const handleClose = () => {
    onClose();
    // after the close animation, so the form doesn't visibly empty
    setTimeout(reset, 350);
  };

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
        problem: problem.trim(),
        desired_outcome: desiredOutcome.trim(),
        priority,
        source_url: window.location.pathname,
        attachment_ids: attachments.flatMap((a) => (a.assetId ? [a.assetId] : [])),
        workspace_slug: workspaceSlug,
      });
      setStep("sent");
    } catch {
      setToast({ type: TOAST_TYPE.ERROR, title: t("helpdesk.suggest.error_title"), message: t("helpdesk.try_again") });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <ModalCore isOpen={isOpen} handleClose={handleClose} position={EModalPosition.TOP} width={EModalWidth.XL}>
      <div className="flex flex-col gap-4 p-5">
        <div className="flex items-center gap-2 text-h5-medium text-primary">
          <Lightbulb className="size-5 text-accent-primary" />
          {t("helpdesk.suggest.title")}
        </div>

        {step === "sent" && (
          <div className="flex flex-col items-start gap-4">
            <div className="flex items-start gap-2 text-body-sm-regular text-secondary">
              <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-success-primary" />
              {t("helpdesk.suggest.sent")}
            </div>
            <div className="flex gap-2 self-end">
              <Button variant="secondary" size="lg" onClick={handleClose}>
                {t("helpdesk.close")}
              </Button>
              <Link href={`/${workspaceSlug}/support`} onClick={handleClose}>
                <Button variant="primary" size="lg">
                  {t("helpdesk.reporter.view_tracking")}
                </Button>
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
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                placeholder={t("helpdesk.suggest.what_placeholder")}
                maxLength={200}
              />
            </label>
            <label className="flex flex-col gap-1.5">
              <span className="text-body-xs-medium text-secondary">{t("helpdesk.suggest.why_label")}</span>
              <TextArea
                value={problem}
                onChange={(event) => setProblem(event.target.value)}
                placeholder={t("helpdesk.suggest.why_placeholder")}
                className="min-h-28"
              />
              <span className={cn("text-caption-sm-regular", problemOk ? "text-success-primary" : "text-tertiary")}>
                {t("helpdesk.suggest.why_hint")}
              </span>
            </label>
            <div className="flex justify-end gap-2">
              <Button variant="secondary" size="lg" onClick={handleClose}>
                {t("helpdesk.cancel")}
              </Button>
              <Button variant="primary" size="lg" disabled={!titleOk || !problemOk} onClick={() => setStep(2)}>
                {t("helpdesk.suggest.next")}
              </Button>
            </div>
          </>
        )}

        {step === 2 && (
          <>
            <label className="flex flex-col gap-1.5">
              <span className="text-body-xs-medium text-secondary">{t("helpdesk.suggest.how_label")}</span>
              <TextArea
                value={desiredOutcome}
                onChange={(event) => setDesiredOutcome(event.target.value)}
                placeholder={t("helpdesk.suggest.how_placeholder")}
                className="min-h-24"
              />
            </label>
            <div className="flex flex-col gap-1.5">
              <span className="text-body-xs-medium text-secondary">{t("helpdesk.suggest.priority_label")}</span>
              <div className="flex gap-2">
                {PRIORITIES.map((value) => (
                  <Button
                    key={value}
                    variant={priority === value ? "primary" : "secondary"}
                    size="lg"
                    onClick={() => setPriority(value)}
                  >
                    {t(`helpdesk.priority.${value}`)}
                  </Button>
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
                  variant="ghost"
                  size="lg"
                  prependIcon={<ImagePlus />}
                  onClick={() => fileInputRef.current?.click()}
                >
                  {t("helpdesk.suggest.add_images")}
                </Button>
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
              <Button variant="ghost" size="lg" onClick={() => setStep(1)}>
                {t("helpdesk.suggest.back")}
              </Button>
              <Button
                variant="primary"
                size="lg"
                loading={submitting}
                disabled={uploading}
                onClick={() => void handleSubmit()}
              >
                {t("helpdesk.suggest.submit")}
              </Button>
            </div>
          </>
        )}
      </div>
    </ModalCore>
  );
}
