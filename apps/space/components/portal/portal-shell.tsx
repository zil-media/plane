/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { ReactNode } from "react";
import { Link, useLocation } from "react-router";
// plane imports
import { useTranslation } from "@plane/i18n";
import { EmptyStateDetailed } from "@plane/propel/empty-state";
import type { TZilPortalBrand } from "@plane/types";
// components
import { UserAvatar } from "@/components/issues/navbar/user-avatar";
// local imports
import { PortalBrandLogo } from "./brand-logo";
import { PORTAL_UNITS, PortalBrandTheme, portalUnit } from "./brand-theme";

type Props = {
  brand?: TZilPortalBrand;
  /** whose look, when there is no single brand (Mis marcas): Zil's by default */
  unit?: string;
  /** "Mis marcas" only shows when the client has more than one */
  showMyBrands?: boolean;
  children: ReactNode;
};

/**
 * The portal's frame, a copy of Ops' (workspace/content-wrapper.tsx + navigation/top-navigation-root.tsx):
 * the top bar on the canvas with the unit's logo, a divider and the brand, and the content in Ops'
 * rounded panel. In the unit's brand (Zil's or Meraki's).
 */
export function PortalShell({ brand, unit, showMyBrands = false, children }: Props) {
  // signing out from a document or a post comes back to it after signing in again
  const location = useLocation();
  const { t } = useTranslation();
  const theme = portalUnit(brand?.unit ?? unit);
  const logo = PORTAL_UNITS[theme];
  return (
    <PortalBrandTheme unit={theme}>
      <div className="relative flex h-screen w-full flex-col overflow-hidden bg-canvas">
        {/* top bar (Ops' TopNavigationRoot) */}
        <div className="z-[27] flex min-h-10 w-full items-center bg-canvas py-1 pr-2 pl-5">
          <div className="flex min-w-0 flex-1 items-center gap-3">
            <img src={logo.logo} alt={logo.name} className="h-4 w-auto shrink-0" />
            {brand && (
              <>
                <div className="mx-1 h-5 w-px shrink-0 border-l border-subtle" />
                <Link to={showMyBrands ? "/portal" : `/portal/${brand.id}`} className="flex min-w-0 items-center gap-2">
                  <PortalBrandLogo name={brand.name} logoUrl={brand.logo_url} color={brand.color} size={24} />
                  <span className="truncate text-14 font-medium text-primary">{brand.name}</span>
                </Link>
              </>
            )}
          </div>
          <div className="flex shrink-0 items-center gap-3">
            {showMyBrands && (
              <Link
                to="/portal"
                className="hidden text-13 whitespace-nowrap text-secondary hover:text-primary sm:block"
              >
                {t("zil_portal.my_brands")}
              </Link>
            )}
            <UserAvatar signOutLabel={t("sign_out")} nextPath={`${location.pathname}${location.search}`} compact />
          </div>
        </div>
        {/* content in Ops' rounded panel */}
        <div className="relative size-full flex-grow overflow-hidden px-2 pb-2">
          <div className="relative flex h-full w-full flex-col overflow-hidden rounded-lg border border-subtle bg-surface-1">
            <main className="size-full overflow-y-auto">
              <div className="mx-auto flex max-w-6xl flex-col gap-6 p-6">{children}</div>
            </main>
          </div>
        </div>
      </div>
    </PortalBrandTheme>
  );
}

type TMessageProps = {
  /** Ops' empty-state illustration */
  assetKey: "no-access" | "invalid-link" | "server-error" | "project" | "page";
  title: string;
  text: string;
};

/** A full-page message (paused access, nothing to show, an error), with Ops' empty state. */
export function PortalMessage({ assetKey, title, text }: TMessageProps) {
  return (
    <div className="grid place-items-center py-10">
      <EmptyStateDetailed assetKey={assetKey} title={title} description={text} />
    </div>
  );
}
