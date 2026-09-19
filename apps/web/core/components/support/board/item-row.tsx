/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { Bug, Lightbulb } from "lucide-react";
import { useTranslation } from "@plane/i18n";
import { calculateTimeAgo, cn } from "@plane/utils";
import type { TBugReport, TFeatureRequest } from "@/services/support.service";
import type { TPhase } from "./phase";
import { TONE_DOT, bugPhase, featurePhase } from "./phase";

export type TBoardItem = { kind: "bug"; item: TBugReport } | { kind: "feature"; item: TFeatureRequest };

export function itemPhase(entry: TBoardItem): TPhase {
  return entry.kind === "bug" ? bugPhase(entry.item) : featurePhase(entry.item);
}

export function itemTitle(entry: TBoardItem): string {
  if (entry.kind === "feature") return entry.item.display_title || entry.item.title;
  return entry.item.display_title || entry.item.description.split("\n")[0].slice(0, 90);
}

type Props = {
  entry: TBoardItem;
  selected: boolean;
  onSelect: () => void;
  showAuthor?: boolean;
};

export function SupportItemRow({ entry, selected, onSelect, showAuthor = false }: Props) {
  const { t } = useTranslation();
  const phase = itemPhase(entry);
  const author = entry.kind === "bug" ? entry.item.reported_by : entry.item.requested_by;
  const Icon = entry.kind === "bug" ? Bug : Lightbulb;

  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        "flex w-full items-center gap-3 rounded-md px-3 py-2 text-left hover:bg-layer-1",
        selected && "bg-layer-1"
      )}
    >
      <Icon className="size-4 shrink-0 text-tertiary" />
      <div className="flex min-w-0 flex-1 flex-col">
        <span className="truncate text-body-xs-medium text-primary">{itemTitle(entry)}</span>
        <span className="truncate text-caption-sm-regular text-tertiary">
          {entry.item.category ? `${entry.item.category} · ` : ""}
          {showAuthor && author ? `${author.display_name} · ` : ""}
          {calculateTimeAgo(entry.item.created_at)}
        </span>
      </div>
      <span className="flex shrink-0 items-center gap-1.5 text-caption-sm-regular text-secondary">
        <span className={cn("size-2 rounded-full", TONE_DOT[phase.tone])} />
        {t(phase.labelKey)}
      </span>
    </button>
  );
}
