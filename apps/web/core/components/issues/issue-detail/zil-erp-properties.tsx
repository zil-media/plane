/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import useSWR from "swr";
import { Building2, ExternalLink, FolderKanban } from "lucide-react";
import { useTranslation } from "@plane/i18n";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import { CustomSearchSelect } from "@plane/ui";
import { cn } from "@plane/utils";
// components
import { SidebarPropertyListItem } from "@/components/common/layout/sidebar/property-list-item";
// services
import type { TZilErpRefKind, TZilIssueErpRefs } from "@/services/zil.service";
import { ZilService } from "@/services/zil.service";

const zilService = new ZilService();
const NONE = "__none__";

type TKindProps = {
  kind: TZilErpRefKind;
  workspaceSlug: string;
  issueId: string;
  refs: TZilIssueErpRefs | undefined;
  disabled: boolean;
  onChange: (refs: TZilIssueErpRefs) => void;
};

function ZilErpRefSelect({ kind, workspaceSlug, issueId, refs, disabled, onChange }: TKindProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  // Options load on first open: the list lives in the ERP and most views never need it.
  const { data, error } = useSWR(open ? `ZIL_ERP_OPTIONS_${workspaceSlug}_${kind}` : null, () =>
    zilService.getErpOptions(workspaceSlug, kind)
  );
  const current = refs?.[kind] ?? null;

  const options = [
    { value: NONE, query: t("common.none"), content: <span className="text-tertiary">{t("common.none")}</span> },
    ...(data?.options ?? []).map((option) => ({
      value: option.id,
      query: `${option.name} ${option.subtitle ?? ""}`,
      content: (
        <span className="flex min-w-0 flex-col">
          <span className="truncate">{option.name}</span>
          {option.subtitle && <span className="truncate text-caption-sm-regular text-tertiary">{option.subtitle}</span>}
        </span>
      ),
    })),
  ];

  const handleChange = async (value: string) => {
    const erpId = value === NONE ? null : value;
    if (erpId === (current?.id ?? null)) return;
    setSaving(true);
    try {
      onChange(await zilService.setIssueErpRef(issueId, kind, erpId));
    } catch {
      setToast({ type: TOAST_TYPE.ERROR, title: t("zil_erp.error_title"), message: t("zil_erp.error") });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex w-full grow items-center gap-1">
      <CustomSearchSelect
        value={current?.id ?? NONE}
        onChange={(value: string) => void handleChange(value)}
        options={options}
        onOpen={() => setOpen(true)}
        disabled={disabled || saving}
        noResultsMessage={error ? t("zil_erp.unavailable") : data ? t("zil_erp.no_options") : t("common.loading")}
        className="min-w-0 grow"
        customButtonClassName="w-full"
        customButton={
          <span
            className={cn(
              "flex h-7.5 w-full items-center rounded-sm px-2 text-left text-body-xs-medium hover:bg-layer-1",
              !current && "text-placeholder"
            )}
          >
            <span className="truncate">{current?.name ?? t("common.none")}</span>
          </span>
        }
      />
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
  const { data: refs, mutate } = useSWR(`ZIL_ISSUE_ERP_REFS_${issueId}`, () => zilService.getIssueErpRefs(issueId), {
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
          disabled={disabled}
          onChange={update}
        />
      </SidebarPropertyListItem>
    </>
  );
}
