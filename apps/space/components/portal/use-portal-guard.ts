/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
// hooks
import { useUser } from "@/hooks/store/use-user";

/** Sends whoever is not signed in to the portal's sign-in, coming back here afterwards. */
export function usePortalGuard() {
  const { data: currentUser, isAuthenticated, isInitializing } = useUser();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const ready = !isInitializing && !!currentUser && isAuthenticated;

  useEffect(() => {
    if (isInitializing || ready) return;
    const query = searchParams.toString();
    const here = query ? `${pathname}?${query}` : pathname;
    router.replace(`/portal/login?next_path=${encodeURIComponent(here)}`);
  }, [isInitializing, ready, pathname, searchParams, router]);

  return ready;
}
