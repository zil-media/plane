/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { ExternalLink } from "lucide-react";
import { useTranslation } from "@plane/i18n";
import { cn, renderFormattedDate, renderFormattedTime } from "@plane/utils";
import { DeployCountdown } from "./deploy-countdown";
import type { TLabel, TTrack } from "./track";

const BANNER_TONE = {
  info: "border-accent-strong bg-accent-subtle text-accent-primary",
  danger: "border-danger-strong bg-danger-subtle text-danger-primary",
  muted: "border-subtle bg-layer-1 text-secondary",
} as const;

function formatAt(at?: string | null) {
  return at ? `${renderFormattedDate(at) ?? ""} ${renderFormattedTime(at, "12-hour")}` : "";
}

/**
 * The phase line: dots, connectors and real timestamps. The active dot pulses (it is being worked
 * on NOW); the warning accent marks "your turn" or "the agent has doubts".
 */
export function PhaseTimeline({ track }: { track: TTrack }) {
  const { t } = useTranslation();
  const text = (label: TLabel) => `${t(label.key, label.params)}${label.note ? ` — ${label.note}` : ""}`;
  const { phases, banner } = track;

  return (
    <div className="flex flex-col gap-4 rounded-md border border-subtle p-3">
      {banner && (
        <div
          className={cn(
            "rounded-md border px-3 py-2 text-body-xs-regular whitespace-pre-wrap",
            BANNER_TONE[banner.tone]
          )}
        >
          {text(banner.label)}
          {banner.note && `\n${banner.note}`}
        </div>
      )}

      {phases.length > 0 && (
        <ol className="flex flex-col">
          {phases.map((phase, index) => {
            const last = index === phases.length - 1;
            return (
              <li key={phase.key} className="flex gap-3">
                <div className="flex flex-col items-center">
                  <span
                    className={cn("mt-1 size-2.5 shrink-0 rounded-full", {
                      "bg-success-primary": phase.state === "done",
                      "animate-pulse bg-warning-primary": phase.state === "active" && phase.waiting,
                      "animate-pulse bg-accent-primary": phase.state === "active" && !phase.waiting,
                      "border border-strong bg-layer-2": phase.state === "pending",
                    })}
                  />
                  {!last && (
                    <span
                      className={cn(
                        "min-h-3 w-px flex-1",
                        phase.state === "done" ? "bg-success-primary/30" : "bg-layer-3"
                      )}
                    />
                  )}
                </div>
                <div className={cn("min-w-0 flex-1", !last && "pb-3")}>
                  <div className="flex flex-wrap items-center gap-2">
                    <span
                      className={cn("text-body-xs-medium", {
                        "text-tertiary": phase.state === "pending",
                        "text-warning-primary": phase.state === "active" && phase.waiting,
                        "text-primary": phase.state === "done" || (phase.state === "active" && !phase.waiting),
                      })}
                    >
                      {text(phase.label)}
                    </span>
                    {phase.at && <span className="text-caption-sm-regular text-tertiary">{formatAt(phase.at)}</span>}
                    {phase.countdown && <DeployCountdown />}
                    {phase.href && (
                      <a
                        href={phase.href}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1 text-caption-sm-regular text-link-primary hover:underline"
                      >
                        <ExternalLink className="size-3" />
                        {t("helpdesk.track.see_pr")}
                      </a>
                    )}
                  </div>
                  {phase.sub?.map((step, stepIndex) => {
                    const latest = phase.state === "active" && stepIndex === (phase.sub?.length ?? 0) - 1;
                    return (
                      <p
                        key={`${step.label.key}-${step.at ?? ""}-${step.label.note ?? ""}`}
                        className={cn(
                          "mt-1 text-caption-sm-regular",
                          step.waiting ? "text-warning-primary" : latest ? "text-primary" : "text-tertiary"
                        )}
                      >
                        {text(step.label)}
                        {step.at && ` · ${formatAt(step.at)}`}
                      </p>
                    );
                  })}
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}
