/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import * as React from "react";

import type { ISvgIcons } from "../type";

// Zil wordmark (rebranded)
export function PlaneWordmark({ width = "146", height = "82", className, color = "currentColor" }: ISvgIcons) {
  return (
    <svg
      width={width}
      height={height}
      viewBox="0 0 57 32"
      fill={color}
      xmlns="http://www.w3.org/2000/svg"
      className={className}
    >
      <path
        d="M12.8857 19.0928H21.4629V32H0L10.1328 19.0928H1.67871V6.18555H23.0186L12.8857 19.0928ZM39.0742 32H26.166V6.18555H39.0742V32ZM57.001 32H44.0938V0H57.001V32Z"
        fill={color}
      />
    </svg>
  );
}
