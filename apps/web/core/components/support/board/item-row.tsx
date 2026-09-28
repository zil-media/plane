/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { ReactNode } from "react";
import { Bug, Lightbulb } from "lucide-react";
import { useTranslation } from "@plane/i18n";
import { cn, renderFormattedDate } from "@plane/utils";
import type { TBugReport, TFeatureRequest } from "@/services/support.service";
import { DeployCountdown } from "./deploy-countdown";
import type { TPhase, TViewer } from "./phase";
import { TONE_CHIP, bugPhase, featurePhase, isMyFeature } from "./phase";

export type TBoardItem = { kind: "bug"; item: TBugReport } | { kind: "feature"; item: TFeatureRequest };

export function itemPhase(entry: TBoardItem): TPhase {
  return entry.kind === "bug" ? bugPhase(entry.item) : featurePhase(entry.item);
}

export function itemTitle(entry: TBoardItem): string {
  if (entry.kind === "feature") return entry.item.display_title || entry.item.title;
  return entry.item.display_title || entry.item.description.split("\n")[0].slice(0, 90);
}

export function PhaseChip({ phase }: { phase: TPhase }) {
  const { t } = useTranslation();
  return (
    <span
      className={cn(
        "shrink-0 rounded-full border px-2 py-0.5 text-caption-sm-regular whitespace-nowrap",
        TONE_CHIP[phase.tone]
      )}
    >
      {t(phase.labelKey)}
    </span>
  );
}

export function Tag({ children }: { children: ReactNode }) {
  return (
    <span className="inline-flex shrink-0 items-center gap-1 rounded-sm border border-subtle px-1.5 py-px text-caption-sm-regular text-secondary">
      {children}
    </span>
  );
}

type Props = {
  entry: TBoardItem;
  viewer: TViewer;
  selected: boolean;
  onSelect: () => void;
  /** Same request loaded more than once: shown as "×N" instead of N rows. */
  count?: number;
};

export function SupportItemRow({ entry, viewer, selected, onSelect, count = 1 }: Props) {
  const { t } = useTranslation();
  const phase = itemPhase(entry);
  const isBug = entry.kind === "bug";
  const Icon = isBug ? Bug : Lightbulb;
  const mine = isBug ? entry.item.reported_by?.id === viewer.userId : isMyFeature(entry.item, viewer);
  const author = isBug ? entry.item.reported_by : entry.item.requested_by;
  const summary =
    entry.item.plain_summary ||
    (isBug
      ? t("helpdesk.board.reported_on", { date: renderFormattedDate(entry.item.created_at) ?? "" })
      : `${author?.display_name ?? ""} · ${renderFormattedDate(entry.item.created_at) ?? ""}`);
  // The agent asks whoever requested it: showing "asks you" to anyone else would be a lie.
  const asksYou = !isBug && entry.item.status === "needs_info" && mine;
  const countdown = isBug ? entry.item.status === "fixed" : entry.item.status === "queued";

  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        "flex w-full flex-col justify-between gap-2 px-4 py-3 text-left hover:bg-layer-1 md:flex-row md:items-center md:gap-4",
        selected && "bg-layer-1"
      )}
    >
      <div className="min-w-0 flex-1">
        <div className="flex min-w-0 flex-wrap items-center gap-2 md:flex-nowrap">
          <Tag>
            <Icon className="size-3" />
            {t(isBug ? "helpdesk.kind.bug" : "helpdesk.kind.feature")}
          </Tag>
          {entry.item.category && <Tag>{entry.item.category}</Tag>}
          <span className="truncate text-body-xs-medium text-primary">{itemTitle(entry)}</span>
          {!mine && author && (
            <Tag>{t("helpdesk.board.by_author", { name: author.first_name || author.display_name })}</Tag>
          )}
          {count > 1 && <span className="shrink-0 text-caption-sm-regular text-tertiary">×{count}</span>}
        </div>
        <p className="mt-0.5 truncate text-caption-sm-regular text-tertiary">{summary}</p>
      </div>
      <div className="flex flex-wrap items-center gap-2 md:shrink-0">
        {asksYou && (
          <span className="rounded-full border border-warning-strong bg-warning-subtle px-2 py-0.5 text-caption-sm-regular text-warning-primary">
            {t("helpdesk.board.asks_you")}
          </span>
        )}
        {countdown && <DeployCountdown />}
        <PhaseChip phase={phase} />
      </div>
    </button>
  );
}
