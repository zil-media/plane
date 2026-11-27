/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { ImageIcon, PlayCircle } from "lucide-react";
// plane imports
import type { TZilPortalPost } from "@plane/types";
import { cn, getFileURL } from "@plane/utils";
// local imports
import { STATUS_CLASS, isVideo, shortDate } from "./helpers";

type Props = {
  post: TZilPortalPost;
  onOpen: (postId: string) => void;
  /** the big card of the "Para revisar" strip */
  large?: boolean;
};

export function PortalPostThumb({ post, className }: { post: TZilPortalPost; className?: string }) {
  const thumb = post.thumbnail;
  const src = thumb ? getFileURL(thumb.url) : undefined;
  if (!thumb || !src)
    return (
      <div className={cn("grid place-items-center bg-layer-1 text-tertiary", className)}>
        <ImageIcon className="size-5" />
      </div>
    );
  if (isVideo(thumb.type))
    return (
      <div className={cn("relative overflow-hidden bg-layer-1", className)}>
        <video src={src} muted preload="metadata" className="size-full object-cover" />
        <PlayCircle className="absolute top-1/2 left-1/2 size-7 -translate-x-1/2 -translate-y-1/2 text-on-color" />
      </div>
    );
  return <img src={src} alt={thumb.name} className={cn("object-cover", className)} loading="lazy" />;
}

/** A post on the calendar: thumbnail, network and date. Nothing more. */
export function PortalPostCard({ post, onOpen, large = false }: Props) {
  return (
    <button
      type="button"
      onClick={() => onOpen(post.id)}
      className={cn(
        "flex w-full overflow-hidden rounded-md border border-subtle bg-surface-1 text-left hover:border-strong-1",
        large ? "flex-col" : "items-center gap-2 p-1"
      )}
    >
      <PortalPostThumb post={post} className={large ? "aspect-square w-full" : "size-9 flex-shrink-0 rounded-sm"} />
      <div className={cn("min-w-0 flex-1", large ? "space-y-1 p-3" : "")}>
        <p className={cn("truncate font-medium text-primary", large ? "text-14" : "text-11")}>{post.name}</p>
        <p className={cn("truncate text-tertiary", large ? "text-13" : "text-11")}>
          {[post.network, post.publish_date ? shortDate(post.publish_date) : null].filter(Boolean).join(" · ")}
        </p>
        {large && (
          <span className={cn("inline-block rounded-sm px-1.5 py-0.5 text-11", STATUS_CLASS[post.status])}>
            {post.status}
          </span>
        )}
      </div>
    </button>
  );
}
