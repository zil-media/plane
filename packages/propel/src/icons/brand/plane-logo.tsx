/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import * as React from "react";

import type { ISvgIcons } from "../type";

// Zil isotype (rebranded)
export function PlaneLogo({ width = "60", height = "37", className, color = "currentColor" }: ISvgIcons) {
  return (
    <svg
      width={width}
      height={height}
      viewBox="0 0 60 37"
      fill={color}
      xmlns="http://www.w3.org/2000/svg"
      className={className}
    >
      <path
        d="M59.2373 0L33.4619 32.8369L30.8994 36.0859H0V0H59.2373ZM3.24902 3.24902V32.8369H29.3682L52.583 3.24902H3.24902Z"
        fill={color}
      />
    </svg>
  );
}
