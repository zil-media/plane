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
import { SitesPortalService } from "@plane/services";
import { getFileURL } from "@plane/utils";
// components
import { UserLoggedIn } from "@/components/account/user-logged-in";
import { LogoSpinner } from "@/components/common/logo-spinner";
import { PortalMessage, PortalShell } from "@/components/portal/portal-shell";
import { usePortalGuard } from "@/components/portal/use-portal-guard";

const portalService = new SitesPortalService();

/** "Mis marcas": straight to the calendar when there is one brand. */
const PortalHomePage = observer(function PortalHomePage() {
  const ready = usePortalGuard();
  const router = useRouter();
  const { data } = useSWR(ready ? "PORTAL_BRANDS" : null, () => portalService.brands());
  const brands = useMemo(() => data?.brands ?? [], [data]);

  useEffect(() => {
    if (brands.length === 1) router.replace(`/portal/${brands[0].id}`);
  }, [brands, router]);

  if (!ready || !data || brands.length === 1)
    return (
      <div className="flex h-screen w-full items-center justify-center bg-surface-1">
        <LogoSpinner />
      </div>
    );

  // someone with no brand portal (the team, or a client whose portals are off)
  if (brands.length === 0) return <UserLoggedIn />;

  return (
    <PortalShell>
      <h1 className="text-18 font-semibold text-primary">Mis marcas</h1>
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
                  {brand.name.charAt(0)}
                </span>
              )}
              <span className="min-w-0 flex-1">
                <span className="block truncate text-14 font-medium text-primary">{brand.name}</span>
                {brand.paused && <span className="text-11 text-tertiary">Acceso en pausa</span>}
              </span>
            </button>
          );
        })}
      </div>
      {brands.every((brand) => brand.paused) && (
        <PortalMessage title="Acceso en pausa" text="Tu acceso está en pausa. Escribile a tu contacto en Zil." />
      )}
    </PortalShell>
  );
});

export default PortalHomePage;
