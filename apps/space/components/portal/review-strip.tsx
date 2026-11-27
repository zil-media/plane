/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// plane imports
import { useTranslation } from "@plane/i18n";
import type { TZilPortalPost } from "@plane/types";
// local imports
import { PortalCalendarIssueBlocks } from "./calendar/issue-blocks";

type Props = {
  posts: TZilPortalPost[];
  onOpen: (postId: string) => void;
};

/** The first thing the client sees: what waits for their opinion, with the calendar's own blocks. */
export function PortalReviewStrip({ posts, onOpen }: Props) {
  const { t } = useTranslation();
  if (posts.length === 0) return null;
  return (
    <section className="space-y-2">
      <h2 className="text-16 font-semibold text-primary">{t("zil_portal.to_review")}</h2>
      <div className="grid grid-cols-1 gap-x-2 rounded-md border border-subtle py-1 sm:grid-cols-2 lg:grid-cols-3">
        <PortalCalendarIssueBlocks posts={posts} onOpen={onOpen} />
      </div>
    </section>
  );
}
