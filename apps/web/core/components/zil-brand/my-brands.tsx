/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { orderBy } from "lodash-es";
import { observer } from "mobx-react";
import Link from "next/link";
// plane imports
import { useTranslation } from "@plane/i18n";
import { Loader } from "@plane/ui";
// hooks
import { useZilMyBrands } from "@/hooks/use-zil-brands";
// local imports
import { ZilBrandLogo } from "./brand-logo";

type Props = {
  workspaceSlug: string;
};

const CHIP = "rounded-sm border border-subtle px-2 py-1 text-secondary hover:text-primary";

/** "Mis marcas": the brands the person works on in this workspace, each with its ways in. */
export const ZilMyBrands = observer(function ZilMyBrands({ workspaceSlug }: Props) {
  const { t } = useTranslation();
  const { brands, isLoading } = useZilMyBrands(workspaceSlug);
  // the live brands first; orderBy (not .sort/.toSorted) keeps oxlint + tsc lib happy
  const visible = orderBy(brands, (brand) => Number(brand.archived));

  return (
    <div className="flex flex-col gap-6 p-6">
      <div className="flex flex-col gap-1">
        <h1 className="text-18 font-semibold text-primary">{t("zil_brand.my_brands")}</h1>
        <p className="text-13 text-tertiary">{t("zil_brand.my_brands_description")}</p>
      </div>

      {isLoading ? (
        <Loader className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <Loader.Item height="120px" />
          <Loader.Item height="120px" />
          <Loader.Item height="120px" />
        </Loader>
      ) : visible.length === 0 ? (
        <div className="flex flex-col gap-1 rounded-md border border-subtle p-6">
          <p className="text-13 text-primary">{t("zil_brand.no_brands")}</p>
          <p className="text-13 text-tertiary">{t("zil_brand.managed_by_zil")}</p>
        </div>
      ) : (
        <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {visible.map((brand) => {
            const base = `/${workspaceSlug}/projects/${brand.project_id}`;
            return (
              <li
                key={brand.project_id}
                className="flex flex-col gap-4 rounded-md border border-subtle p-4 data-[archived=true]:opacity-60"
                data-archived={brand.archived}
              >
                <Link
                  href={brand.kind === "brand" ? `${base}/brand` : `${base}/pages`}
                  className="flex items-center gap-3"
                >
                  <ZilBrandLogo name={brand.name} logoUrl={brand.logo_url} color={brand.color} />
                  <div className="flex min-w-0 flex-col">
                    <span className="truncate text-14 font-medium text-primary">{brand.name}</span>
                    <span className="text-12 text-tertiary">
                      {brand.kind === "migration" ? t("zil_brand.migration") : brand.identifier}
                      {brand.archived && ` · ${t("zil_brand.archived")}`}
                    </span>
                  </div>
                </Link>
                <div className="flex flex-wrap gap-2 text-12">
                  <Link href={`${base}/issues`} className={CHIP}>
                    {t("sidebar.work_items")}
                  </Link>
                  <Link href={`${base}/pages`} className={CHIP}>
                    {t("sidebar.pages")}
                  </Link>
                  {brand.kind === "brand" && (
                    <Link href={`${base}/brand`} className={CHIP}>
                      {t("sidebar.brand")}
                    </Link>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
});
