/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import useSWR from "swr";
import { supportService } from "@/services/support.service";

export const SUPPORT_FEATURE_FLAGS_KEY = "SUPPORT_FEATURE_FLAGS";

/**
 * Gate for features the feature agent builds: they ship dark and an admin turns them on from
 * the support board. Unknown or loading flags read as off.
 */
export function useFeatureFlag(key: string): boolean {
  const { data } = useSWR(SUPPORT_FEATURE_FLAGS_KEY, () => supportService.enabledFlags(), {
    revalidateOnFocus: false,
    dedupingInterval: 60_000,
  });
  return data?.enabled.includes(key) ?? false;
}
