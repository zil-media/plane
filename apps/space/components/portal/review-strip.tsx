/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// plane imports
import type { TZilPortalPost } from "@plane/types";
// local imports
import { PortalPostCard } from "./post-card";

type Props = {
  posts: TZilPortalPost[];
  onOpen: (postId: string) => void;
};

/** The first thing the client sees: what waits for their opinion. */
export function PortalReviewStrip({ posts, onOpen }: Props) {
  if (posts.length === 0) return null;
  return (
    <section className="space-y-3">
      <h2 className="text-16 font-semibold text-primary">Para revisar</h2>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        {posts.map((post) => (
          <PortalPostCard key={post.id} post={post} onOpen={onOpen} large />
        ))}
      </div>
    </section>
  );
}
