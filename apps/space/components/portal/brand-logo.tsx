/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
// plane imports
import { cn, getFileURL } from "@plane/utils";

type Props = {
  name: string;
  logoUrl: string | null | undefined;
  color: string | null | undefined;
  size?: number;
  className?: string;
};

/** A copy of Ops' brand tile (apps/web/core/components/zil-brand/brand-logo.tsx): the logo, or the initial on the brand color. */
export function PortalBrandLogo({ name, logoUrl, color, size = 40, className }: Props) {
  const [failed, setFailed] = useState(false);
  const src = logoUrl ? getFileURL(logoUrl) : undefined;
  if (src && !failed) {
    return (
      <img
        src={src}
        alt={name}
        width={size}
        height={size}
        onError={() => setFailed(true)}
        className={cn("flex-shrink-0 rounded-md border border-subtle bg-white object-contain", className)}
        style={{ width: size, height: size }}
      />
    );
  }
  return (
    <span
      aria-hidden
      className={cn("flex flex-shrink-0 items-center justify-center rounded-md font-semibold text-white", className)}
      style={{ width: size, height: size, backgroundColor: color || "#6D86FF", fontSize: size * 0.42 }}
    >
      {(name || "?").trim().charAt(0).toUpperCase()}
    </span>
  );
}
