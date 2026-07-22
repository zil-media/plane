/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

type TZilLogoProps = {
  className?: string;
};

// Zil brand wordmark (the "ZIL" mark). Static, single-path SVG that inherits
// its color from `currentColor`, so a `text-*` class controls the fill.
// Use this as the standalone Zil brand mark (replaces the generic PlaneLogo).
// Kept in sync with apps/web/core/components/common/zil-logo.tsx — apps/space
// cannot import across app boundaries, so this is a local copy.
const ZIL_PATH =
  "M12.8857 19.0928H21.4629V32H0L10.1328 19.0928H1.67871V6.18555H23.0186L12.8857 19.0928ZM39.0742 32H26.166V6.18555H39.0742V32ZM57.001 32H44.0938V0H57.001V32Z";

export function ZilLogo({ className = "" }: TZilLogoProps) {
  return (
    <svg
      viewBox="0 0 57 32"
      className={className}
      fill="currentColor"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      <path d={ZIL_PATH} />
    </svg>
  );
}
