/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import type { ClipboardEvent } from "react";
import { toJpeg } from "html-to-image";
import Link from "next/link";
import { Bug, CheckCircle2, ImagePlus, Loader2, X } from "lucide-react";
import { useTranslation } from "@plane/i18n";
import { Button } from "@plane/propel/button";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import { EFileAssetType } from "@plane/types";
import { TextArea, ToggleSwitch } from "@plane/ui";
import { getConsoleEntries } from "@/lib/support/console-capture";
import { getSystemInfo, getViewport } from "@/lib/support/system-info";
import { supportService } from "@/services/support.service";
import { MAX_ATTACHMENTS, compressImage, uploadSupportImage } from "./attachments";

type TImage = {
  key: string;
  preview: string;
  assetId?: string;
  status: "uploading" | "done" | "error";
};

type Props = {
  isOpen: boolean;
  onClose: () => void;
  workspaceSlug: string;
};

const CAPTURE_TIMEOUT_MS = 10_000;

function isDesktop() {
  return window.innerWidth >= 768 && !window.matchMedia("(pointer: coarse)").matches;
}

function withTimeout<T>(promise: Promise<T>, ms: number): Promise<T> {
  return Promise.race([promise, new Promise<T>((_, reject) => setTimeout(() => reject(new Error("timeout")), ms))]);
}

/** The page as the user sees it, minus this panel and the things html-to-image can't draw. */
function capturePage(): Promise<string> {
  return toJpeg(document.body, {
    quality: 0.7,
    pixelRatio: 1,
    cacheBust: true,
    filter: (node) =>
      !(node instanceof HTMLElement) ||
      (node.dataset.supportPanel === undefined && !["IFRAME", "VIDEO"].includes(node.tagName)),
  });
}

export function BugReporter(props: Props) {
  const { isOpen, onClose, workspaceSlug } = props;
  const { t } = useTranslation();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [description, setDescription] = useState("");
  const [urgent, setUrgent] = useState(false);
  const [images, setImages] = useState<TImage[]>([]);
  const [capturing, setCapturing] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [sent, setSent] = useState(false);

  // Source of truth for the attachment cap: state updaters run later than this code needs to know.
  const countRef = useRef(0);
  const capturedRef = useRef(false);

  const reset = useCallback(() => {
    setDescription("");
    setUrgent(false);
    countRef.current = 0;
    setImages((current) => {
      current.forEach((image) => URL.revokeObjectURL(image.preview));
      return [];
    });
    setSent(false);
  }, []);

  const addImage = useCallback(
    async (file: File) => {
      if (countRef.current >= MAX_ATTACHMENTS) return;
      countRef.current += 1;
      const key = `${Date.now()}-${Math.random()}`;
      const preview = URL.createObjectURL(file);
      setImages((current) => [...current, { key, preview, status: "uploading" }]);
      try {
        const assetId = await uploadSupportImage(workspaceSlug, file, EFileAssetType.BUG_REPORT_ATTACHMENT);
        setImages((current) => current.map((i) => (i.key === key ? { ...i, assetId, status: "done" } : i)));
      } catch {
        setImages((current) => current.map((i) => (i.key === key ? { ...i, status: "error" } : i)));
      }
    },
    [workspaceSlug]
  );

  // Desktop: grab the screen the moment the panel opens, while it still shows the problem.
  useEffect(() => {
    if (!isOpen) {
      capturedRef.current = false;
      return;
    }
    if (capturedRef.current || countRef.current > 0 || !isDesktop()) return;
    capturedRef.current = true;
    let cancelled = false;
    setCapturing(true);
    withTimeout(capturePage(), CAPTURE_TIMEOUT_MS)
      .then((dataUrl) => compressImage(dataUrl, "pantalla.jpg"))
      .then((file) => (cancelled ? undefined : addImage(file)))
      .catch(() => undefined)
      .finally(() => !cancelled && setCapturing(false));
    return () => {
      cancelled = true;
    };
  }, [isOpen, addImage]);

  useEffect(() => {
    if (!isOpen) return;
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [isOpen, onClose]);

  const handlePaste = (event: ClipboardEvent<HTMLTextAreaElement>) => {
    const files = Array.from(event.clipboardData.items)
      .filter((item) => item.type.startsWith("image/"))
      .map((item) => item.getAsFile())
      .filter((file): file is File => file !== null);
    if (files.length === 0) return;
    event.preventDefault();
    files.forEach((file) => void compressImage(file, file.name).then(addImage));
  };

  const handleFiles = (files: FileList | null) => {
    Array.from(files ?? [])
      .filter((file) => file.type.startsWith("image/"))
      .forEach((file) => void compressImage(file, file.name).then(addImage));
  };

  const removeImage = (key: string) => {
    countRef.current = Math.max(0, countRef.current - 1);
    setImages((current) => {
      const image = current.find((i) => i.key === key);
      if (image) URL.revokeObjectURL(image.preview);
      return current.filter((i) => i.key !== key);
    });
  };

  const uploading = images.some((image) => image.status === "uploading");

  const handleSubmit = async () => {
    if (!description.trim() || uploading) return;
    setSubmitting(true);
    try {
      await supportService.createBugReport({
        description: description.trim(),
        urgent,
        url: window.location.pathname + window.location.search,
        user_agent: window.navigator.userAgent,
        viewport: getViewport(),
        system_info: getSystemInfo(),
        console_logs: getConsoleEntries(),
        attachment_ids: images.flatMap((image) => (image.assetId ? [image.assetId] : [])),
        workspace_slug: workspaceSlug,
      });
      setSent(true);
    } catch {
      setToast({ type: TOAST_TYPE.ERROR, title: t("helpdesk.reporter.error_title"), message: t("helpdesk.try_again") });
    } finally {
      setSubmitting(false);
    }
  };

  const close = () => {
    if (sent) reset();
    onClose();
  };

  if (!isOpen) return null;

  return (
    <div
      data-support-panel=""
      role="dialog"
      aria-label={t("helpdesk.reporter.title")}
      className="fixed right-4 bottom-4 z-40 flex w-[380px] max-w-[calc(100vw-2rem)] flex-col gap-3 rounded-lg border border-subtle bg-surface-1 p-4 shadow-raised-200"
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-body-sm-medium text-primary">
          <Bug className="size-4" />
          {t("helpdesk.reporter.title")}
        </div>
        <button
          type="button"
          onClick={close}
          aria-label={t("helpdesk.close")}
          className="grid size-6 place-items-center rounded-sm text-tertiary hover:bg-layer-1"
        >
          <X className="size-4" />
        </button>
      </div>

      {sent ? (
        <div className="flex flex-col items-start gap-3">
          <div className="flex items-start gap-2 text-body-xs-regular text-secondary">
            <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-success-primary" />
            {t("helpdesk.reporter.sent")}
          </div>
          <div className="flex gap-2">
            <Link href={`/${workspaceSlug}/support`} onClick={close}>
              <Button variant="secondary" size="lg">
                {t("helpdesk.reporter.view_tracking")}
              </Button>
            </Link>
            <Button variant="ghost" size="lg" onClick={reset}>
              {t("helpdesk.reporter.report_another")}
            </Button>
          </div>
        </div>
      ) : (
        <>
          <TextArea
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            onPaste={handlePaste}
            placeholder={t("helpdesk.reporter.placeholder")}
            className="min-h-28 w-full text-body-xs-regular"
          />

          <div className="flex flex-wrap items-center gap-2">
            {images.map((image) => (
              <div key={image.key} className="relative size-14 overflow-hidden rounded-sm border border-subtle">
                <img src={image.preview} alt="" className="size-full object-cover" />
                {image.status === "uploading" && (
                  <div className="absolute inset-0 grid place-items-center bg-backdrop">
                    <Loader2 className="size-4 animate-spin text-on-color" />
                  </div>
                )}
                {image.status === "error" && <div className="absolute inset-0 bg-danger-subtle" />}
                <button
                  type="button"
                  onClick={() => removeImage(image.key)}
                  aria-label={t("helpdesk.reporter.remove_image")}
                  className="absolute top-0.5 right-0.5 grid size-4 place-items-center rounded-full bg-surface-1 text-secondary"
                >
                  <X className="size-3" />
                </button>
              </div>
            ))}
            {capturing && <Loader2 className="size-4 animate-spin text-tertiary" />}
            {images.length < MAX_ATTACHMENTS && (
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                className="grid size-14 place-items-center rounded-sm border border-dashed border-subtle text-tertiary hover:bg-layer-1"
                aria-label={t("helpdesk.reporter.add_image")}
              >
                <ImagePlus className="size-4" />
              </button>
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
          <p className="text-caption-sm-regular text-tertiary">{t("helpdesk.reporter.images_hint")}</p>

          <div className="flex items-center justify-between gap-3 rounded-md bg-layer-1 px-3 py-2">
            <span className="flex flex-col">
              <span className="text-body-xs-medium text-primary">{t("helpdesk.reporter.urgent")}</span>
              <span className="text-caption-sm-regular text-tertiary">{t("helpdesk.reporter.urgent_hint")}</span>
            </span>
            <ToggleSwitch
              value={urgent}
              onChange={() => setUrgent((value) => !value)}
              size="sm"
              label={t("helpdesk.reporter.urgent")}
            />
          </div>

          <div className="flex items-center justify-between gap-2">
            <Link
              href={`/${workspaceSlug}/support`}
              onClick={close}
              className="text-caption-sm-regular text-link-primary hover:underline"
            >
              {t("helpdesk.reporter.my_reports")}
            </Link>
            <Button
              variant="primary"
              size="lg"
              onClick={() => void handleSubmit()}
              loading={submitting}
              disabled={!description.trim() || uploading}
            >
              {t("helpdesk.reporter.submit")}
            </Button>
          </div>
        </>
      )}
    </div>
  );
}
