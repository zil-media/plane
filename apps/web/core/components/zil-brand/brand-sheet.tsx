/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { ReactNode } from "react";
import { observer } from "mobx-react";
import { ExternalLink, Phone, UserRound } from "lucide-react";
// plane imports
import { useTranslation } from "@plane/i18n";
import { Loader } from "@plane/ui";
// hooks
import { useZilProjectBrand } from "@/hooks/use-zil-brands";
// local imports
import { ZilBrandLogo } from "./brand-logo";

type Props = {
  workspaceSlug: string;
  projectId: string;
};

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-2">
      <h3 className="text-13 font-medium text-tertiary">{title}</h3>
      {children}
    </section>
  );
}

function Empty({ children }: { children: ReactNode }) {
  return <p className="text-13 text-placeholder">{children}</p>;
}

function Notice({ children }: { children: ReactNode }) {
  return <p className="rounded-md border border-subtle bg-layer-1 px-4 py-3 text-13 text-secondary">{children}</p>;
}

function formatDate(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString();
}

/** The "Marca" tab: the brand's specifications strip, assets, team and calls, read live from Zil. */
export const ZilBrandSheet = observer(function ZilBrandSheet({ workspaceSlug, projectId }: Props) {
  const { t } = useTranslation();
  const { data, isLoading } = useZilProjectBrand(workspaceSlug, projectId);

  if (isLoading || !data) {
    return (
      <Loader className="flex flex-col gap-4 p-6">
        <Loader.Item height="56px" width="320px" />
        <Loader.Item height="88px" />
        <Loader.Item height="200px" />
      </Loader>
    );
  }

  const { brand, sheet, unavailable } = data;
  const strip = sheet?.specs?.strip?.slice(0, 3) ?? [];
  const otherProjects = sheet?.projects ?? [];
  const purposeLabel = (purpose: string) =>
    purpose === "kickoff" || purpose === "operations" ? t(`zil_brand.purpose_${purpose}`) : purpose;

  return (
    <div className="flex flex-col gap-6 p-6">
      <div className="flex items-center gap-4">
        <ZilBrandLogo
          name={brand.name}
          logoUrl={sheet?.brand.logoUrl || brand.logo_url}
          color={sheet?.brand.color || brand.color}
          size={56}
        />
        <div className="flex flex-col gap-1">
          <h2 className="text-18 font-semibold text-primary">{sheet?.brand.name || brand.name}</h2>
          <span className="text-13 text-tertiary">
            {brand.identifier}
            {brand.archived && ` · ${t("zil_brand.archived")}`}
          </span>
        </div>
      </div>

      {unavailable && <Notice>{t("zil_brand.unavailable")}</Notice>}
      {!unavailable && !sheet && <Notice>{t("zil_brand.no_sheet")}</Notice>}

      {sheet && (
        <>
          <Section title={t("zil_brand.specs")}>
            {strip.length === 0 ? (
              <Empty>{t("zil_brand.no_specs")}</Empty>
            ) : (
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                {strip.map((item) => (
                  <div key={item.key} className="flex flex-col gap-1 rounded-md border border-subtle p-4">
                    <span className="text-11 text-tertiary">{item.label}</span>
                    <span className="text-18 font-semibold text-primary">{item.value}</span>
                    {item.hint && <span className="text-11 text-tertiary">{item.hint}</span>}
                  </div>
                ))}
              </div>
            )}
          </Section>

          <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
            <Section title={t("zil_brand.team")}>
              {!sheet.team?.length ? (
                <Empty>{t("zil_brand.no_team")}</Empty>
              ) : (
                <ul className="flex flex-col divide-y divide-subtle rounded-md border border-subtle">
                  {sheet.team.map((person) => (
                    <li key={person.email} className="flex items-center gap-3 px-3 py-2">
                      <UserRound className="size-4 flex-shrink-0 text-tertiary" />
                      <div className="flex min-w-0 flex-col">
                        <span className="truncate text-13 text-primary">{person.name || person.email}</span>
                        {person.role && <span className="truncate text-11 text-tertiary">{person.role}</span>}
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </Section>

            <Section title={t("zil_brand.assets")}>
              {!sheet.assets?.length ? (
                <Empty>{t("zil_brand.no_assets")}</Empty>
              ) : (
                <ul className="flex flex-col divide-y divide-subtle rounded-md border border-subtle">
                  {sheet.assets.map((asset) => (
                    <li key={asset.id} className="flex items-center justify-between gap-3 px-3 py-2">
                      <div className="flex min-w-0 flex-col">
                        <span className="truncate text-13 text-primary">{asset.name}</span>
                        <span className="text-11 text-tertiary">{asset.type}</span>
                      </div>
                      {asset.url && (
                        <a
                          href={asset.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="flex-shrink-0 text-tertiary hover:text-primary"
                          aria-label={asset.name}
                        >
                          <ExternalLink className="size-4" />
                        </a>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </Section>
          </div>

          <Section title={t("zil_brand.calls")}>
            {!sheet.calls?.length ? (
              <Empty>{t("zil_brand.no_calls")}</Empty>
            ) : (
              <ul className="flex flex-col divide-y divide-subtle rounded-md border border-subtle">
                {sheet.calls.map((call) => (
                  <li key={call.id} className="flex flex-col gap-1 px-3 py-2">
                    <div className="flex items-center gap-2">
                      <Phone className="size-3.5 flex-shrink-0 text-tertiary" />
                      <span className="truncate text-13 text-primary">{call.title}</span>
                      <span className="ml-auto flex-shrink-0 text-11 text-tertiary">
                        {formatDate(call.date)}
                        {call.purpose && ` · ${purposeLabel(call.purpose)}`}
                      </span>
                    </div>
                    {call.summary && <p className="line-clamp-3 text-12 text-secondary">{call.summary}</p>}
                  </li>
                ))}
              </ul>
            )}
          </Section>

          {otherProjects.length > 0 && (
            <Section title={t("zil_brand.other_bus")}>
              <div className="flex flex-wrap gap-1.5">
                {otherProjects.map((other) => (
                  <span
                    key={other.workspaceSlug}
                    className="inline-flex items-center rounded-sm border border-subtle px-1.5 py-0.5 text-11 text-secondary"
                  >
                    {other.businessUnit || other.workspaceSlug}
                  </span>
                ))}
              </div>
            </Section>
          )}
        </>
      )}
    </div>
  );
});
