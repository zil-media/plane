/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { ReactNode } from "react";
import { Briefcase, FileText, Mail, Phone, UserRound } from "lucide-react";
// plane imports
import { useTranslation } from "@plane/i18n";
import type { TZilClientProfile } from "@plane/types";

type Props = {
  profile: TZilClientProfile;
};

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-2">
      <h4 className="text-13 font-medium text-tertiary">{title}</h4>
      {children}
    </section>
  );
}

function Empty({ children }: { children: ReactNode }) {
  return <p className="text-13 text-placeholder">{children}</p>;
}

export function ZilClientInfo({ profile }: Props) {
  const { t } = useTranslation();
  const { info, projects, services } = profile;
  const viaLabel = (via: "project" | "contract" | "grant") => t(`page_tree.zil_client.profile.via_${via}`);
  const contacts = [
    ...(info.primaryContact
      ? [{ ...info.primaryContact, role: t("page_tree.zil_client.profile.primary_contact") }]
      : []),
    ...info.operationalContacts.map((c) => ({ ...c, phone: "" })),
  ];

  return (
    <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
      <div className="flex flex-col gap-6">
        <div className="grid grid-cols-2 gap-4 rounded-md border border-subtle p-4">
          <div className="flex flex-col gap-0.5">
            <span className="text-11 text-tertiary">{t("page_tree.zil_client.profile.status")}</span>
            <span className="text-13 text-primary">{info.lifecycleStatus || "—"}</span>
          </div>
          <div className="flex flex-col gap-0.5">
            <span className="text-11 text-tertiary">{t("page_tree.zil_client.profile.country")}</span>
            <span className="text-13 text-primary">{info.country || "—"}</span>
          </div>
          <div className="col-span-2 flex flex-col gap-0.5">
            <span className="text-11 text-tertiary">{t("page_tree.zil_client.profile.owner_bu")}</span>
            <span className="text-13 text-primary">{info.businessUnit?.label || "—"}</span>
          </div>
          {info.relatedBusinessUnits.length > 0 && (
            <div className="col-span-2 flex flex-col gap-1">
              <span className="text-11 text-tertiary">{t("page_tree.zil_client.profile.related_bus")}</span>
              <div className="flex flex-wrap gap-1.5">
                {info.relatedBusinessUnits.map((bu) => (
                  <span
                    key={bu.slug}
                    className="inline-flex items-center gap-1 rounded-sm border border-subtle px-1.5 py-0.5 text-11 text-secondary"
                  >
                    {bu.label}
                    <span className="text-tertiary">· {bu.via.map(viaLabel).join(", ")}</span>
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>

        <Section title={t("page_tree.zil_client.profile.operational_contacts")}>
          {contacts.length === 0 ? (
            <Empty>{t("page_tree.zil_client.profile.no_contacts")}</Empty>
          ) : (
            <ul className="flex flex-col divide-y divide-subtle rounded-md border border-subtle">
              {contacts.map((contact) => (
                <li
                  key={`${contact.role}-${contact.email}-${contact.name}`}
                  className="flex items-start gap-2 px-3 py-2"
                >
                  <UserRound className="mt-0.5 size-3.5 flex-shrink-0 text-tertiary" />
                  <div className="flex min-w-0 flex-col">
                    <span className="truncate text-13 text-primary">
                      {contact.name || contact.email}
                      {contact.role && <span className="text-tertiary"> · {contact.role}</span>}
                    </span>
                    {contact.email && (
                      <a
                        href={`mailto:${contact.email}`}
                        className="flex items-center gap-1 truncate text-11 text-secondary hover:text-primary"
                      >
                        <Mail className="size-3 flex-shrink-0" />
                        {contact.email}
                      </a>
                    )}
                    {contact.phone && (
                      <span className="flex items-center gap-1 text-11 text-secondary">
                        <Phone className="size-3 flex-shrink-0" />
                        {contact.phone}
                      </span>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Section>
      </div>

      <div className="flex flex-col gap-6">
        <Section title={t("page_tree.zil_client.profile.services")}>
          {services.length === 0 ? (
            <Empty>{t("page_tree.zil_client.profile.no_services")}</Empty>
          ) : (
            <ul className="flex flex-col divide-y divide-subtle rounded-md border border-subtle">
              {services.map((service) => (
                <li key={service.id} className="flex items-start gap-2 px-3 py-2">
                  <FileText className="mt-0.5 size-3.5 flex-shrink-0 text-tertiary" />
                  <div className="flex min-w-0 flex-col">
                    <span className="text-13 text-primary">{service.titles.join(", ") || "—"}</span>
                    <span className="text-11 text-tertiary">
                      {service.endDate
                        ? t("page_tree.zil_client.profile.period", { start: service.startDate, end: service.endDate })
                        : t("page_tree.zil_client.profile.since", { start: service.startDate })}
                      {service.autoRenewal && ` · ${t("page_tree.zil_client.profile.auto_renewal")}`}
                    </span>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Section>

        <Section title={t("page_tree.zil_client.profile.projects")}>
          {projects.length === 0 ? (
            <Empty>{t("page_tree.zil_client.profile.no_projects")}</Empty>
          ) : (
            <ul className="flex flex-col divide-y divide-subtle rounded-md border border-subtle">
              {projects.map((project) => (
                <li key={project.id} className="flex items-center gap-2 px-3 py-2">
                  <Briefcase className="size-3.5 flex-shrink-0 text-tertiary" />
                  <span className="min-w-0 flex-grow truncate text-13 text-primary">{project.name}</span>
                  {project.service && <span className="flex-shrink-0 text-11 text-tertiary">{project.service}</span>}
                  {project.businessUnitSlug && (
                    <span className="flex-shrink-0 text-11 text-tertiary">{project.businessUnitSlug}</span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Section>
      </div>
    </div>
  );
}
