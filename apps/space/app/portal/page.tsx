/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useMemo } from "react";
import { observer } from "mobx-react";
import { Link } from "react-router";
import { useRouter } from "next/navigation";
import useSWR from "swr";
// plane imports
import { useTranslation } from "@plane/i18n";
import { SitesPortalService } from "@plane/services";
// components
import { LogoSpinner } from "@/components/common/logo-spinner";
import { PortalBrandLogo } from "@/components/portal/brand-logo";
import { PortalMessage, PortalShell } from "@/components/portal/portal-shell";
import { usePortalGuard } from "@/components/portal/use-portal-guard";

const portalService = new SitesPortalService();

/** "Mis marcas", a copy of Ops' (zil-brand/my-brands.tsx): straight to the calendar when there is one brand. */
const PortalHomePage = observer(function PortalHomePage() {
  const { t } = useTranslation();
  const ready = usePortalGuard();
  const router = useRouter();
  const { data, error } = useSWR(ready ? "PORTAL_BRANDS" : null, () => portalService.brands());
  const brands = useMemo(() => data?.brands ?? [], [data]);
  // one look for the page: the unit when all the brands share it, Zil's otherwise
  const unit = brands.length > 0 && brands.every((brand) => brand.unit === brands[0].unit) ? brands[0].unit : "zil";

  useEffect(() => {
    if (brands.length === 1) router.replace(`/portal/${brands[0].id}`);
  }, [brands, router]);

  if (error)
    return (
      <PortalShell>
        <PortalMessage
          assetKey="server-error"
          title={t("zil_portal.brands_error_title")}
          text={t("zil_portal.try_again")}
        />
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
        <PortalMessage
          assetKey="project"
          title={t("zil_portal.no_portal_title")}
          text={t("zil_portal.no_portal_text")}
        />
      </PortalShell>
    );

  if (brands.every((brand) => brand.paused))
    return (
      <PortalShell unit={unit}>
        <PortalMessage assetKey="no-access" title={t("zil_portal.paused_title")} text={t("zil_portal.paused_text")} />
      </PortalShell>
    );

  return (
    <PortalShell unit={unit}>
      <div className="flex flex-col gap-1">
        <h1 className="text-18 font-semibold text-primary">{t("zil_portal.my_brands")}</h1>
        <p className="text-13 text-tertiary">{t("zil_portal.my_brands_description")}</p>
      </div>
      <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {brands.map((brand) => (
          <li
            key={brand.id}
            className="flex flex-col gap-4 rounded-md border border-subtle p-4 data-[paused=true]:opacity-60"
            data-paused={brand.paused}
          >
            <Link to={`/portal/${brand.id}`} className="flex items-center gap-3">
              <PortalBrandLogo name={brand.name} logoUrl={brand.logo_url} color={brand.color} />
              <div className="flex min-w-0 flex-col">
                <span className="truncate text-14 font-medium text-primary">{brand.name}</span>
                {brand.paused && <span className="text-12 text-tertiary">{t("zil_portal.paused_title")}</span>}
              </div>
            </Link>
          </li>
        ))}
      </ul>
    </PortalShell>
  );
});

export default PortalHomePage;
