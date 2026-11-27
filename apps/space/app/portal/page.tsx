/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useMemo } from "react";
import { observer } from "mobx-react";
import { useRouter } from "next/navigation";
import useSWR from "swr";
// plane imports
import { useTranslation } from "@plane/i18n";
import { SitesPortalService } from "@plane/services";
import { getFileURL } from "@plane/utils";
// components
import { LogoSpinner } from "@/components/common/logo-spinner";
import { PortalMessage, PortalShell } from "@/components/portal/portal-shell";
import { usePortalGuard } from "@/components/portal/use-portal-guard";

const portalService = new SitesPortalService();

/** "Mis marcas": straight to the calendar when there is one brand. */
const PortalHomePage = observer(function PortalHomePage() {
  const { t } = useTranslation();
  const ready = usePortalGuard();
  const router = useRouter();
  const { data, error } = useSWR(ready ? "PORTAL_BRANDS" : null, () => portalService.brands());
  const brands = useMemo(() => data?.brands ?? [], [data]);

  useEffect(() => {
    if (brands.length === 1) router.replace(`/portal/${brands[0].id}`);
  }, [brands, router]);

  if (error)
    return (
      <PortalShell>
        <PortalMessage title={t("zil_portal.brands_error_title")} text={t("zil_portal.try_again")} />
      </PortalShell>
    );

  if (!ready || !data || brands.length === 1)
    return (
      <div className="flex h-screen w-full items-center justify-center bg-surface-1">
        <LogoSpinner />
      </div>
    );

  // no active portal (a client whose portals are off, or someone of the team)
  if (brands.length === 0)
    return (
      <PortalShell>
        <PortalMessage title={t("zil_portal.no_portal_title")} text={t("zil_portal.no_portal_text")} />
      </PortalShell>
    );

  return (
    <PortalShell>
      <h1 className="text-18 font-semibold text-primary">{t("zil_portal.my_brands")}</h1>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {brands.map((brand) => {
          const logo = brand.logo_url ? getFileURL(brand.logo_url) : undefined;
          return (
            <button
              key={brand.id}
              type="button"
              onClick={() => router.push(`/portal/${brand.id}`)}
              className="flex items-center gap-3 rounded-md border border-subtle p-4 text-left hover:border-strong-1"
            >
              {logo ? (
                <img src={logo} alt={brand.name} className="size-10 rounded-md object-contain" />
              ) : (
                <span
                  className="grid size-10 place-items-center rounded-md text-14 font-semibold text-on-color"
                  style={{ backgroundColor: brand.color ?? undefined }}
                >
                  {(brand.name || "?").charAt(0)}
                </span>
              )}
              <span className="min-w-0 flex-1">
                <span className="block truncate text-14 font-medium text-primary">{brand.name}</span>
                {brand.paused && <span className="text-11 text-tertiary">{t("zil_portal.paused_title")}</span>}
              </span>
            </button>
          );
        })}
      </div>
      {brands.every((brand) => brand.paused) && (
        <PortalMessage title={t("zil_portal.paused_title")} text={t("zil_portal.paused_text")} />
      )}
    </PortalShell>
  );
});

export default PortalHomePage;
