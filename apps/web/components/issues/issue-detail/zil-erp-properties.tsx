/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import useSWR from "swr";
import { Building2, ExternalLink, FolderKanban } from "lucide-react";
import { useTranslation } from "@plane/i18n";
import { Select } from "@plane/blocks/select";
import { setToast } from "@plane/blocks/toast";
import { cn } from "@plane/utils";
// components
import { SidebarPropertyListItem } from "@/components/common/layout/sidebar/property-list-item";
// services
import type { TZilErpRefKind, TZilIssueErpRefs } from "@/services/zil.service";
import { ZilService } from "@/services/zil.service";
import { ZilBrandLogo } from "@/components/zil-brand/brand-logo";

const zilService = new ZilService();
const NONE = "__none__";

type TErpSelectOption = {
  id: string;
  name: string;
  subtitle?: string | null;
  logoUrl?: string | null;
  searchText: string;
  isNone?: boolean;
};

type TKindProps = {
  kind: TZilErpRefKind;
  workspaceSlug: string;
  issueId: string;
  refs: TZilIssueErpRefs | undefined;
  /** The ERP didn't answer: the link is unknown, which must not read as "none". */
  unavailable: boolean;
  disabled: boolean;
  onChange: (refs: TZilIssueErpRefs) => void;
};

function ZilErpRefSelect({ kind, workspaceSlug, issueId, refs, unavailable, disabled, onChange }: TKindProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  // Projects only list those of the work item's Cliente (and brand), so the pair stays consistent.
  const filterClientId = kind === "project" ? (refs?.client?.id ?? null) : null;
  const filterBrandId = kind === "project" ? (refs?.client?.brand?.id ?? null) : null;
  // Options load on first open: the list lives in the ERP and most views never need it.
  const { data, error } = useSWR(
    open ? `ZIL_ERP_OPTIONS_${workspaceSlug}_${kind}_${filterClientId ?? ""}_${filterBrandId ?? ""}` : null,
    () => zilService.getErpOptions(workspaceSlug, kind, { clientId: filterClientId, brandId: filterBrandId })
  );
  const current = refs?.[kind] ?? null;
  const currentBrand = current?.brand ?? null;
  // A client picked with one of its brands is the row `${clientId}:${brandId}`.
  const currentValue = current ? (currentBrand ? `${current.id}:${currentBrand.id}` : current.id) : NONE;

  const options: TErpSelectOption[] = [
    { id: NONE, name: t("common.none"), searchText: t("common.none"), isNone: true },
    ...(data?.options ?? []).map((option) => ({
      id: option.id,
      name: option.name,
      subtitle: option.subtitle,
      logoUrl: option.logo_url,
      searchText: `${option.name} ${option.subtitle ?? ""}`,
    })),
  ];
  const selectedOption = options.find((option) => option.id === currentValue) ?? {
    id: currentValue,
    name: current?.name ?? "",
    searchText: current?.name ?? "",
  };

  const handleChange = async (value: string) => {
    if (value === currentValue) return;
    const option = data?.options.find((o) => o.id === value);
    const erpId = value === NONE ? null : (option?.erp_id ?? value);
    const brandId = value === NONE ? null : (option?.brand_id ?? null);
    setSaving(true);
    try {
      onChange(await zilService.setIssueErpRef(issueId, kind, erpId, brandId));
    } catch {
      setToast({ type: "error", title: t("zil_erp.error_title"), message: t("zil_erp.error") });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex w-full grow items-center gap-1">
      <Select<TErpSelectOption>
        getValues={() => options}
        value={selectedOption}
        onChange={(value: string) => void handleChange(value)}
        getOptionValue={(option) => option.id}
        getOptionLabel={(option) => option.name}
        getOptionSearchText={(option) => option.searchText}
        getOptionIcon={(option) =>
          kind === "client" && !option.isNone ? (
            <ZilBrandLogo name={option.name} logoUrl={option.logoUrl || null} size={20} />
          ) : undefined
        }
        getOptionDescription={(option) => option.subtitle}
        onOpenChange={(isOpen) => {
          if (isOpen) setOpen(true);
        }}
        disabled={disabled || saving || unavailable}
        emptyMessage={error ? t("zil_erp.unavailable") : data ? t("zil_erp.no_options") : t("common.loading")}
        pinSelected={false}
        placeholder={t("common.none")}
      >
        <Select.Trigger variant="select-ghost-lg" className="w-full min-w-0 grow">
          <span className={cn("flex min-w-0 items-center text-left", !current && "text-placeholder")}>
            {current && kind === "client" && (
              <ZilBrandLogo
                name={currentBrand?.name ?? current.name}
                logoUrl={current.logo_url || null}
                size={16}
                className="mr-1.5"
              />
            )}
            {current && currentBrand ? (
              <span className="flex min-w-0 items-baseline gap-1">
                <span className="truncate">{currentBrand.name}</span>
                <span className="shrink-0 truncate text-caption-sm-regular text-tertiary">{current.name}</span>
              </span>
            ) : (
              <span className="truncate">
                {current?.name ?? (unavailable ? t("zil_erp.unavailable_short") : t("common.none"))}
              </span>
            )}
          </span>
        </Select.Trigger>
      </Select>
      {current?.url && (
        <a
          href={current.url}
          target="_blank"
          rel="noopener noreferrer"
          aria-label={t("zil_erp.open_in_zil")}
          className="grid size-6 shrink-0 place-items-center rounded-sm text-tertiary hover:bg-layer-1 hover:text-primary"
        >
          <ExternalLink className="size-3.5" />
        </a>
      )}
    </div>
  );
}

type Props = {
  workspaceSlug: string;
  issueId: string;
  disabled: boolean;
};

/**
 * The ERP client and project a work item belongs to. The link is owned by Zil Workspace (it lives
 * on the client/project, which also shows it); Ops only reads it and asks the ERP to change it.
 */
export function IssueZilErpProperties({ workspaceSlug, issueId, disabled }: Props) {
  const { t } = useTranslation();
  const {
    data: refs,
    error,
    mutate,
  } = useSWR(`ZIL_ISSUE_ERP_REFS_${issueId}`, () => zilService.getIssueErpRefs(issueId), {
    revalidateOnFocus: false,
    shouldRetryOnError: false,
  });
  const update = (next: TZilIssueErpRefs) => void mutate(next, { revalidate: false });

  return (
    <>
      <SidebarPropertyListItem icon={Building2} label={t("zil_erp.client")}>
        <ZilErpRefSelect
          kind="client"
          workspaceSlug={workspaceSlug}
          issueId={issueId}
          refs={refs}
          unavailable={!!error}
          disabled={disabled}
          onChange={update}
        />
      </SidebarPropertyListItem>
      <SidebarPropertyListItem icon={FolderKanban} label={t("zil_erp.project")}>
        <ZilErpRefSelect
          kind="project"
          workspaceSlug={workspaceSlug}
          issueId={issueId}
          refs={refs}
          unavailable={!!error}
          disabled={disabled}
          onChange={update}
        />
      </SidebarPropertyListItem>
    </>
  );
}
