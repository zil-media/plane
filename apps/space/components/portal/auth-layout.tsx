/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { ReactNode } from "react";
// local imports
import { PORTAL_UNITS, PortalBrandTheme } from "./brand-theme";
import type { TPortalUnit } from "./brand-theme";

type Props = {
  unit: TPortalUnit;
  children: ReactNode;
};

/**
 * The portal's way in: a copy of Ops' sign-in (apps/web/core/components/auth-screens/auth-base.tsx
 * and auth-gradient.tsx): the floating gradient with the logo on the left, the form on a glass panel
 * on the right. In the unit's colors and logo (Zil's or Meraki's) instead of Ops'.
 */
export function PortalAuthLayout({ unit, children }: Props) {
  const brand = PORTAL_UNITS[unit];
  const [first, second, third] = brand.gradient;
  return (
    <PortalBrandTheme unit={unit}>
      <div className="relative flex h-screen w-screen overflow-hidden bg-canvas">
        {/* the unit's gradient, floating behind everything (Ops' AuthGradient) */}
        <div className="pointer-events-none absolute inset-0 overflow-hidden" aria-hidden>
          <span className="portal-orb portal-orb--a" />
          <span className="portal-orb portal-orb--b" />
          <span className="portal-orb portal-orb--c" />
          <style>{`
            .portal-orb { position: absolute; border-radius: 9999px; filter: blur(72px); opacity: 0.55; will-change: transform; }
            .portal-orb--a { width: 34rem; height: 34rem; left: -6rem; top: -4rem;
              background: radial-gradient(circle at 30% 30%, ${first}, transparent 70%); animation: portal-orb-a 18s ease-in-out infinite; }
            .portal-orb--b { width: 30rem; height: 30rem; left: 22%; top: 30%;
              background: radial-gradient(circle at 30% 30%, ${second}, transparent 70%); animation: portal-orb-b 22s ease-in-out infinite; }
            .portal-orb--c { width: 28rem; height: 28rem; left: 2%; bottom: -8rem;
              background: radial-gradient(circle at 30% 30%, ${third}, transparent 70%); animation: portal-orb-c 20s ease-in-out infinite; }
            @keyframes portal-orb-a { 0%, 100% { transform: translate(0, 0) scale(1); } 50% { transform: translate(4rem, 3rem) scale(1.12); } }
            @keyframes portal-orb-b { 0%, 100% { transform: translate(0, 0) scale(1); } 50% { transform: translate(-3rem, 4rem) scale(1.08); } }
            @keyframes portal-orb-c { 0%, 100% { transform: translate(0, 0) scale(1); } 50% { transform: translate(3rem, -3rem) scale(1.1); } }
          `}</style>
        </div>

        {/* Left — branding panel (desktop only), as in Ops */}
        <div className="relative z-10 hidden w-1/2 flex-col items-center justify-center p-12 lg:flex xl:p-16">
          <img src={brand.logoOnGradient} alt={brand.name} className="h-16 w-auto" />
        </div>

        {/* Right — the form on Ops' glass panel */}
        <div className="relative z-10 flex h-full w-full flex-col overflow-y-auto border-subtle bg-surface-1/80 px-8 pt-6 pb-10 backdrop-blur-xl sm:px-12 lg:w-1/2 lg:border-l">
          <div className="flex flex-1 flex-col items-center justify-center py-10">
            <div className="w-full max-w-sm">
              <img src={brand.logo} alt={brand.name} className="mb-8 h-7 w-auto lg:hidden" />
              {children}
            </div>
          </div>
        </div>
      </div>
    </PortalBrandTheme>
  );
}
