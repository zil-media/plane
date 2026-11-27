/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// plane imports
import type { TZilPortalPost } from "@plane/types";
// local imports
import { PortalCalendarIssueBlock } from "./issue-block";

type Props = {
  posts: TZilPortalPost[];
  onOpen: (postId: string) => void;
  openPostId?: string | null;
};

/** The posts of one day: a copy of Ops' CalendarIssueBlocks, without quick add or pagination. */
export function PortalCalendarIssueBlocks({ posts, onOpen, openPostId }: Props) {
  return (
    <>
      {posts.map((post) => (
        <div key={post.id} className="relative cursor-pointer p-1 px-2">
          <PortalCalendarIssueBlock post={post} onOpen={onOpen} isOpen={openPostId === post.id} />
        </div>
      ))}
    </>
  );
}
