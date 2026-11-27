/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { ReactNode } from "react";
import { Link, useLocation } from "react-router";
// plane imports
import { useTranslation } from "@plane/i18n";
import type { TZilPortalBrand } from "@plane/types";
import { getFileURL } from "@plane/utils";
// components
import { ZilLogo } from "@/components/common/zil-logo";
import { UserAvatar } from "@/components/issues/navbar/user-avatar";

type Props = {
  brand?: TZilPortalBrand;
  /** "Mis marcas" only shows when the client has more than one */
  showMyBrands?: boolean;
  children: ReactNode;
};

/** The portal's one screen: the brand's logo on top, nothing else to learn. */
export function PortalShell({ brand, showMyBrands = false, children }: Props) {
  // signing out from a document or a post comes back to it after signing in again
  const location = useLocation();
  const { t } = useTranslation();
  const logo = brand?.logo_url ? getFileURL(brand.logo_url) : undefined;
  return (
    <div className="min-h-screen bg-surface-1">
      <header className="sticky top-0 z-10 border-b border-subtle bg-surface-1">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-3 sm:px-6">
          <div className="flex min-w-0 items-center gap-3">
            {brand ? (
              <>
                {logo ? (
                  <img src={logo} alt={brand.name} className="size-9 flex-shrink-0 rounded-md object-contain" />
                ) : (
                  <span
                    className="grid size-9 flex-shrink-0 place-items-center rounded-md text-14 font-semibold text-on-color"
                    style={{ backgroundColor: brand.color ?? undefined }}
                  >
                    {(brand.name || "?").charAt(0)}
                  </span>
                )}
                <span className="truncate text-16 font-semibold text-primary">{brand.name}</span>
              </>
            ) : (
              <ZilLogo className="h-5 w-auto text-primary" />
            )}
          </div>
          <div className="flex items-center gap-3">
            {showMyBrands && (
              <Link to="/portal" className="text-13 whitespace-nowrap text-secondary hover:text-primary">
                {t("zil_portal.my_brands")}
              </Link>
            )}
            <UserAvatar signOutLabel={t("sign_out")} nextPath={`${location.pathname}${location.search}`} />
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-6xl space-y-6 px-4 py-6 sm:px-6">{children}</main>
    </div>
  );
}

/** A full-page message (paused access, nothing to show). */
export function PortalMessage({ title, text }: { title: string; text: string }) {
  return (
    <div className="mx-auto max-w-md space-y-2 py-16 text-center">
      <h1 className="text-18 font-semibold text-primary">{title}</h1>
      <p className="text-14 text-secondary">{text}</p>
    </div>
  );
}
