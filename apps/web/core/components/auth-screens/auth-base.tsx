/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import React from "react";
import Link from "next/link";
import { PlaneLockup } from "@plane/propel/icons";
import { AuthRoot } from "@/components/account/auth-forms/auth-root";
import { EAuthModes } from "@/helpers/authentication.helper";
import { AuthGradient } from "./auth-gradient";
import { AuthHeader } from "./header";
import { ZilWorkspaceSignIn } from "./zil-workspace-sign-in";

type AuthBaseProps = {
  authType: EAuthModes;
};

export function AuthBase({ authType }: AuthBaseProps) {
  // Ops authenticates exclusively through Zil Workspace SSO. For sign-in we
  // replace the native credential form with the Workspace SSO panel (identity
  // is never collected here). Other modes keep the default form.
  const isSignIn = authType === EAuthModes.SIGN_IN;
  return (
    <div className="relative flex h-screen w-screen overflow-hidden bg-canvas">
      {/* Animated brand orb gradient behind everything */}
      <AuthGradient />

      {/* Left — branding panel (desktop only). Transparent so the gradient shows through. */}
      <div className="relative z-10 hidden w-1/2 flex-col items-center justify-center p-12 lg:flex xl:p-16">
        <Link href="/" className="flex-shrink-0">
          <PlaneLockup height={64} width={114} className="text-primary" />
        </Link>
      </div>

      {/* Right — form panel. Glass surface that adapts to the active theme. */}
      <div className="relative z-10 flex h-full w-full flex-col overflow-y-auto border-subtle bg-surface-1/80 px-8 pt-6 pb-10 backdrop-blur-xl sm:px-12 lg:w-1/2 lg:border-l">
        {isSignIn ? (
          <ZilWorkspaceSignIn />
        ) : (
          <>
            <AuthHeader type={authType} />
            <AuthRoot authMode={authType} />
          </>
        )}
      </div>
    </div>
  );
}
