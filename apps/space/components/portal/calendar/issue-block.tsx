/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// plane imports
import type { TZilPortalPost } from "@plane/types";
import { cn } from "@plane/utils";

type Props = {
  post: TZilPortalPost;
  onOpen: (postId: string) => void;
  isOpen?: boolean;
};

/**
 * A post on the portal calendar: a copy of Ops' calendar work item block
 * (apps/web/core/components/issues/issue-layouts/calendar/issue-block.tsx), read-only: the state's
 * color bar and the name; no identifier, menu or preview card.
 */
export function PortalCalendarIssueBlock({ post, onOpen, isOpen = false }: Props) {
  return (
    <button
      type="button"
      onClick={() => onOpen(post.id)}
      className="block w-full rounded-sm border-b border-subtle text-left text-13 text-primary hover:border-subtle-1 md:border-[1px]"
    >
      <div
        className={cn(
          "group/calendar-block flex h-10 w-full items-center justify-between gap-1.5 rounded-sm bg-surface-1 px-4 py-1.5 hover:bg-surface-2 md:h-8 md:px-1",
          { "border border-accent-strong hover:border-accent-strong": isOpen }
        )}
      >
        <div className="flex h-full items-center gap-1.5 truncate">
          <span
            className="h-full w-0.5 flex-shrink-0 rounded-sm"
            style={{ backgroundColor: post.status_color ?? undefined }}
          />
          <div className="truncate text-13 font-medium md:text-11 md:font-regular">{post.name}</div>
        </div>
      </div>
    </button>
  );
}
