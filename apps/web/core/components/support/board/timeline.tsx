/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { orderBy } from "lodash-es";
import { Bot, MessageSquare, User } from "lucide-react";
import { useTranslation } from "@plane/i18n";
import { calculateTimeAgo } from "@plane/utils";
import type { TSupportComment } from "@/services/support.service";

type Props = {
  comments?: TSupportComment[];
};

/** The conversation, oldest first. The agent's milestones live in the phase line above. */
export function SupportTimeline({ comments = [] }: Props) {
  const { t } = useTranslation();
  if (comments.length === 0) return null;

  return (
    <div className="flex flex-col gap-3">
      <span className="text-caption-sm-medium text-primary">{t("helpdesk.detail.conversation")}</span>
      <ol className="flex flex-col gap-3">
        {orderBy(comments, ["at"], ["asc"]).map((comment) => (
          <li key={`${comment.at}-${comment.author_name}`} className="flex gap-2.5">
            {comment.role === "agent" ? (
              <Bot className="mt-0.5 size-3.5 shrink-0 text-tertiary" />
            ) : comment.role === "admin" ? (
              <MessageSquare className="mt-0.5 size-3.5 shrink-0 text-tertiary" />
            ) : (
              <User className="mt-0.5 size-3.5 shrink-0 text-tertiary" />
            )}
            <div className="flex min-w-0 flex-col gap-0.5">
              <div className="flex items-baseline gap-2">
                <span className="text-body-xs-medium text-primary">
                  {comment.role === "agent" ? t("helpdesk.timeline.support_team") : comment.author_name}
                </span>
                <span className="text-caption-sm-regular text-tertiary">{calculateTimeAgo(comment.at)}</span>
              </div>
              {comment.text && (
                <p className="text-body-xs-regular break-words whitespace-pre-wrap text-secondary">{comment.text}</p>
              )}
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}
