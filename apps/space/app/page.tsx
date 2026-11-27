/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect } from "react";
import { observer } from "mobx-react";
import { useSearchParams, useRouter } from "next/navigation";
// plane imports
import { isValidNextPath } from "@plane/utils";
// components
import { LogoSpinner } from "@/components/common/logo-spinner";
import { AuthView } from "@/components/views";
// hooks
import { useUser } from "@/hooks/store/use-user";
import type { Route } from "./+types/page";

export const headers: Route.HeadersFunction = () => ({
  "X-Frame-Options": "SAMEORIGIN",
});

const HomePage = observer(function HomePage() {
  const { data: currentUser, isAuthenticated, isInitializing } = useUser();
  const searchParams = useSearchParams();
  const router = useRouter();
  const nextPath = searchParams.get("next_path");

  // the brand client portal has its own sign-in (a failed one comes back here with error_code)
  const toPortal = !!nextPath && nextPath.startsWith("/portal") && isValidNextPath(nextPath);

  useEffect(() => {
    if (isInitializing) return;
    if (currentUser && isAuthenticated) {
      if (nextPath && isValidNextPath(nextPath)) router.replace(nextPath);
      // signed in with nothing to open: the brand portal (or "one more step" for the team)
      else router.replace("/portal");
    } else if (toPortal) {
      router.replace(`/portal/login?${searchParams.toString()}`);
    }
  }, [currentUser, isAuthenticated, isInitializing, nextPath, toPortal, searchParams, router]);

  if (isInitializing)
    return (
      <div className="flex h-screen min-h-[500px] w-full items-center justify-center bg-surface-1">
        <LogoSpinner />
      </div>
    );

  if ((currentUser && isAuthenticated) || toPortal)
    return (
      <div className="flex h-screen min-h-[500px] w-full items-center justify-center bg-surface-1">
        <LogoSpinner />
      </div>
    );

  return <AuthView />;
});

export default HomePage;
