/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { orderBy } from "lodash-es";
import { Bot, MessageSquare, User } from "lucide-react";
import { useTranslation } from "@plane/i18n";
import { calculateTimeAgo, cn } from "@plane/utils";
import type { TProgressEntry, TSupportComment } from "@/services/support.service";
import type { TTone } from "./phase";
import { TONE_DOT } from "./phase";

type TEntry =
  | { kind: "progress"; at: string; phase: string; note: string }
  | { kind: "comment"; at: string; role: TSupportComment["role"]; author: string; text: string };

type Props = {
  progress?: TProgressEntry[];
  comments?: TSupportComment[];
};

/** Everything that happened to a request, oldest first: agent milestones and the conversation. */
export function SupportTimeline({ progress = [], comments = [] }: Props) {
  const { t } = useTranslation();
  const entries: TEntry[] = orderBy<TEntry>(
    [
      ...progress.map((p) => ({ kind: "progress" as const, at: p.at, phase: p.phase, note: p.note })),
      ...comments.map((c) => ({
        kind: "comment" as const,
        at: c.at,
        role: c.role,
        author: c.author_name,
        text: c.text,
      })),
    ],
    ["at"],
    ["asc"]
  );

  if (entries.length === 0) return null;

  return (
    <ol className="flex flex-col gap-3">
      {entries.map((entry) => (
        <li
          key={`${entry.kind}-${entry.at}-${entry.kind === "progress" ? entry.phase : entry.author}`}
          className="flex gap-2.5"
        >
          {entry.kind === "progress" ? (
            <span
              className={cn(
                "mt-1.5 size-2 shrink-0 rounded-full",
                TONE_DOT[(entry.phase === "dudas" ? "waiting" : "progress") as TTone]
              )}
            />
          ) : entry.role === "agent" ? (
            <Bot className="mt-0.5 size-3.5 shrink-0 text-tertiary" />
          ) : entry.role === "admin" ? (
            <MessageSquare className="mt-0.5 size-3.5 shrink-0 text-tertiary" />
          ) : (
            <User className="mt-0.5 size-3.5 shrink-0 text-tertiary" />
          )}
          <div className="flex min-w-0 flex-col gap-0.5">
            <div className="flex items-baseline gap-2">
              <span className="text-body-xs-medium text-primary">
                {entry.kind === "progress"
                  ? t(`helpdesk.progress.${entry.phase}`)
                  : entry.role === "agent"
                    ? t("helpdesk.timeline.support_team")
                    : entry.author}
              </span>
              <span className="text-caption-sm-regular text-tertiary">{calculateTimeAgo(entry.at)}</span>
            </div>
            {(entry.kind === "progress" ? entry.note : entry.text) && (
              <p className="text-body-xs-regular break-words whitespace-pre-wrap text-secondary">
                {entry.kind === "progress" ? entry.note : entry.text}
              </p>
            )}
          </div>
        </li>
      ))}
    </ol>
  );
}
