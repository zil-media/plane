/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useState } from "react";

type TPlatformOS = {
  isMobile: boolean;
  platform: string;
};

const DEFAULT_PLATFORM_OS: TPlatformOS = { isMobile: false, platform: "" };

const detectPlatformOS = (): TPlatformOS => {
  const userAgent = window.navigator.userAgent;
  const isMobile = /iPhone|iPad|iPod|Android/i.test(userAgent);
  let platform = "";

  if (!isMobile) {
    if (userAgent.indexOf("Win") !== -1) {
      platform = "Windows";
    } else if (userAgent.indexOf("Mac") !== -1) {
      platform = "MacOS";
    } else if (userAgent.indexOf("Linux") !== -1) {
      platform = "Linux";
    } else {
      platform = "Unknown";
    }
  }
  return { isMobile, platform };
};

export const usePlatformOS = () => {
  // `window.navigator.userAgent` is unavailable in the build-time prerender and
  // reads differently on every client, so it can't drive the first render's
  // output without mismatching the hydrated shell (same class of bug as the
  // `mounted` guard in app/provider.tsx). Read it only after mount.
  const [platformOS, setPlatformOS] = useState<TPlatformOS>(DEFAULT_PLATFORM_OS);

  useEffect(() => {
    setPlatformOS(detectPlatformOS());
  }, []);

  return platformOS;
};
