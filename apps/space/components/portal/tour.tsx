/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { CalendarDays, Clapperboard, FileText, MessageSquareText, Send } from "lucide-react";
import type { LucideIcon } from "lucide-react";
// plane imports
import { useTranslation } from "@plane/i18n";
import { Button } from "@plane/propel/button";
import { CloseIcon } from "@plane/propel/icons";
import type { TZilPortalDocument, TZilPortalFolder, TZilPortalPost, TZilPortalReview } from "@plane/types";
// assets
import demoVideo from "@/app/assets/portal-tour/demo.mp4?url";
// local imports
import { PortalCalendarIssueBlocks } from "./calendar/issue-blocks";
import { DraftRow, ReviewBanner } from "./changes";
import { DocumentTree } from "./documents";
import { PortalReviewStrip } from "./review-strip";
import { PortalVideoPlayer } from "./video-player";

type TTourStep = "calendar" | "review" | "video" | "changes" | "documents";

const STEPS: { key: TTourStep; Icon: LucideIcon }[] = [
  { key: "calendar", Icon: CalendarDays },
  { key: "review", Icon: MessageSquareText },
  { key: "video", Icon: Clapperboard },
  { key: "changes", Icon: Send },
  { key: "documents", Icon: FileText },
];

// --- sample data: only the tour shows it, and it goes with the tour -----------------------------

const DAY = 24 * 60 * 60 * 1000;
const isoDay = (offset: number) => new Date(Date.now() + offset * DAY).toISOString().slice(0, 10);

const samplePost = (id: string, name: string, offset: number, status: TZilPortalPost["status"], color: string) => ({
  id,
  name,
  publish_date: isoDay(offset),
  status,
  status_color: color,
  network: "Instagram",
  labels: [],
  thumbnail: null,
});

const SAMPLE_REVIEW: TZilPortalReview = {
  rounds: 1,
  used: 0,
  left: 1,
  deadline: new Date(Date.now() + 9 * DAY + 4 * 60 * 60 * 1000).toISOString(),
  open: true,
  reason: null,
};

/**
 * The portal's welcome for a client's first visit, a copy of Ops' product tour
 * (components/onboarding/tour): a welcome card, then one step per part of the portal. Where Ops
 * shows a picture, each step shows the portal's own pieces with sample data (a calendar, a video
 * with its comments marked, a round of changes), which go away with the tour. Skippable at any step.
 */
export function PortalTour({ brandName, onComplete }: { brandName: string; onComplete: () => void }) {
  const { t } = useTranslation();
  const [step, setStep] = useState<TTourStep | "welcome">("welcome");
  const index = STEPS.findIndex((item) => item.key === step);

  const posts: TZilPortalPost[] = [
    samplePost("tour-1", t("zil_portal.tour.sample_post_1"), 2, "review", "#F59E0B"),
    samplePost("tour-2", t("zil_portal.tour.sample_post_2"), 5, "scheduled", "#5271DD"),
    samplePost("tour-3", t("zil_portal.tour.sample_post_3"), -3, "published", "#46A758"),
  ];
  const folders: TZilPortalFolder[] = [
    { id: "tour-folder", name: t("zil_portal.tour.sample_folder"), parent_id: null },
  ];
  const documents: TZilPortalDocument[] = [
    { id: "tour-doc-1", name: t("zil_portal.tour.sample_doc_1"), updated_at: isoDay(-1), parent_id: null },
    { id: "tour-doc-2", name: t("zil_portal.tour.sample_doc_2"), updated_at: isoDay(-6), parent_id: "tour-folder" },
  ];
  const markers = [
    { id: "tour-m1", at: 4, author: t("zil_portal.tour.sample_author"), text: t("zil_portal.tour.sample_change_1") },
    { id: "tour-m2", at: 15, author: t("zil_portal.tour.sample_author"), text: t("zil_portal.tour.sample_change_2") },
  ];

  const sample = {
    calendar: (
      <div className="w-full max-w-md rounded-md border border-subtle bg-surface-1 py-1">
        <PortalCalendarIssueBlocks posts={posts} onOpen={() => undefined} />
      </div>
    ),
    review: (
      <div className="w-full max-w-md">
        <PortalReviewStrip posts={[{ ...posts[0], review: SAMPLE_REVIEW }]} onOpen={() => undefined} />
      </div>
    ),
    video: (
      <div className="w-full max-w-lg overflow-hidden rounded-md">
        <PortalVideoPlayer
          src={demoVideo}
          name={t("zil_portal.tour.sample_post_1")}
          markers={markers}
          onPlayer={() => undefined}
          onTime={() => undefined}
          onMarker={() => undefined}
        />
      </div>
    ),
    changes: (
      <div className="w-full max-w-md space-y-2">
        <ReviewBanner review={SAMPLE_REVIEW} />
        <ul className="space-y-2">
          <DraftRow
            draft={{
              id: "tour-d1",
              text: t("zil_portal.tour.sample_change_1"),
              moment: { media: "tour", at: 4, label: "0:04" },
              created_at: isoDay(0),
            }}
            onSave={async () => undefined}
            onDelete={async () => undefined}
          />
        </ul>
        <div className="flex justify-end">
          <Button variant="primary" size="sm" tabIndex={-1} className="pointer-events-none">
            {t("zil_portal.send_changes", { count: 1 })}
          </Button>
        </div>
      </div>
    ),
    documents: (
      <ul className="w-full max-w-md divide-y divide-subtle-1 overflow-hidden rounded-md border border-subtle bg-surface-1">
        <DocumentTree parentId={null} depth={0} folders={folders} documents={documents} onOpen={() => undefined} />
      </ul>
    ),
  };

  if (step === "welcome")
    return (
      <div className="w-4/5 overflow-hidden rounded-[10px] bg-surface-1 md:w-1/2 lg:w-2/5">
        <div className="h-full overflow-hidden">
          <div className="grid h-40 place-items-center bg-accent-primary">
            <CalendarDays className="size-10 text-on-color" aria-hidden="true" />
          </div>
          <div className="flex flex-col overflow-y-auto p-6">
            <h3 className="font-semibold sm:text-18">{t("zil_portal.tour.welcome_title", { brand: brandName })}</h3>
            <p className="mt-3 text-13 text-secondary">{t("zil_portal.tour.welcome_text")}</p>
            <div className="mt-12 flex flex-wrap items-center gap-6">
              <Button variant="primary" onClick={() => setStep("calendar")}>
                {t("zil_portal.tour.start")}
              </Button>
              <button
                type="button"
                className="bg-transparent text-11 font-medium text-accent-primary outline-subtle-1"
                onClick={onComplete}
              >
                {t("zil_portal.tour.skip")}
              </button>
            </div>
          </div>
        </div>
      </div>
    );

  const current = STEPS[index];
  const previous = STEPS[index - 1];
  const next = STEPS[index + 1];
  return (
    <div className="relative grid max-h-[90vh] w-[92%] grid-cols-10 overflow-hidden rounded-[10px] bg-surface-1 md:w-3/4 lg:w-3/5">
      <button
        type="button"
        aria-label={t("zil_portal.close")}
        className="absolute top-3 right-3 z-10 cursor-pointer rounded-full border border-strong bg-surface-1 p-1"
        onClick={onComplete}
      >
        <CloseIcon className="h-3 w-3 text-primary" />
      </button>
      {/* steps (Ops' TourSidebar) */}
      <div className="col-span-3 hidden bg-surface-2 p-8 lg:block">
        <h3 className="text-16 font-medium">{t("zil_portal.tour.sidebar_title")}</h3>
        <div className="mt-8 space-y-5">
          {STEPS.map((item) => (
            <button
              type="button"
              key={item.key}
              className={`flex w-full cursor-pointer items-center gap-2 border-l-[3px] py-0.5 pr-2 pl-3 text-left text-13 font-medium ${
                step === item.key ? "border-accent-strong text-accent-primary" : "border-transparent text-secondary"
              }`}
              onClick={() => setStep(item.key)}
            >
              <item.Icon className="h-4 w-4" aria-hidden="true" />
              {t(`zil_portal.tour.${item.key}_label`)}
            </button>
          ))}
        </div>
      </div>
      <div className="col-span-10 flex max-h-[90vh] flex-col overflow-hidden lg:col-span-7">
        {/* where Ops shows a picture: the portal itself, with sample data */}
        <div className="flex min-h-56 flex-shrink-0 items-center justify-center overflow-hidden bg-layer-1 p-6">
          {sample[current.key]}
        </div>
        <div className="flex flex-col overflow-y-auto p-4">
          <h3 className="font-semibold sm:text-18">{t(`zil_portal.tour.${current.key}_title`)}</h3>
          <p className="mt-3 text-13 text-secondary">{t(`zil_portal.tour.${current.key}_text`)}</p>
          <p className="mt-2 text-11 text-placeholder">{t("zil_portal.tour.sample_note")}</p>
          <div className="mt-6 flex items-end justify-between gap-4">
            <div className="flex items-center gap-4">
              {previous && (
                <Button variant="secondary" onClick={() => setStep(previous.key)}>
                  {t("zil_portal.tour.back")}
                </Button>
              )}
              {next ? (
                <Button variant="primary" onClick={() => setStep(next.key)}>
                  {t("zil_portal.tour.next")}
                </Button>
              ) : (
                <Button variant="primary" onClick={onComplete}>
                  {t("zil_portal.tour.done")}
                </Button>
              )}
            </div>
            <span className="text-11 text-tertiary">
              {index + 1} / {STEPS.length}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
