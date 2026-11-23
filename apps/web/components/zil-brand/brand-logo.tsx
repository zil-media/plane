/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { cn } from "@plane/utils";

type Props = {
  name: string;
  logoUrl?: string | null;
  color?: string | null;
  size?: number;
  className?: string;
};

/** The brand's logo, or its initial on the brand's color when there is none (or it fails to load). */
export function ZilBrandLogo({ name, logoUrl, color, size = 40, className }: Props) {
  const [failed, setFailed] = useState(false);
  if (logoUrl && !failed) {
    return (
      <img
        src={logoUrl}
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
