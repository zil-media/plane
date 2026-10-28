/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useRef, useState } from "react";
import type { KeyboardEvent, ReactNode } from "react";
import { observer } from "mobx-react";
import { Check, ExternalLink, FileText, FolderOpen, Pencil, Phone, Plus, Trash2, UserRound, X } from "lucide-react";
// plane imports
import { EUserPermissions, EUserPermissionsLevel } from "@plane/constants";
import { useTranslation } from "@plane/i18n";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import { Avatar, Input, Loader } from "@plane/ui";
import { getFileURL } from "@plane/utils";
// components
import { MemberDropdown } from "@/components/dropdowns/member/dropdown";
// hooks
import { useMember } from "@/hooks/store/use-member";
import { useUserPermissions } from "@/hooks/store/user";
import { useZilProjectBrand } from "@/hooks/use-zil-brands";
import type { TZilBrandLink, TZilBrandOps } from "@/services/zil-brand.service";
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

function OpsCard({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-2 rounded-md border border-subtle p-4">
      <span className="text-11 font-medium tracking-wide text-tertiary uppercase">{label}</span>
      {children}
    </div>
  );
}

/** The people picked for a role, by name: clicking the list opens the picker when editable. */
const PeopleList = observer(function PeopleList({ memberIds }: { memberIds: string[] }) {
  const { t } = useTranslation();
  const { getUserDetails } = useMember();

  if (memberIds.length === 0)
    return (
      <span className="flex items-center gap-2 py-0.5 text-13 text-placeholder">
        <UserRound className="size-4 flex-shrink-0" />
        {t("zil_brand.unassigned")}
      </span>
    );
  return (
    <ul className="flex flex-col gap-1.5">
      {memberIds.map((memberId) => {
        const member = getUserDetails(memberId);
        return (
          <li key={memberId} className="flex min-w-0 items-center gap-2">
            <Avatar name={member?.display_name} src={getFileURL(member?.avatar_url ?? "")} size="md" />
            <span className="truncate text-13 text-primary">{member?.display_name ?? "…"}</span>
          </li>
        );
      })}
    </ul>
  );
});

type TPeopleFieldProps = {
  projectId: string;
  memberIds: string[];
  isEditable: boolean;
  onChange: (memberIds: string[]) => void;
};

function PeopleField({ projectId, memberIds, isEditable, onChange }: TPeopleFieldProps) {
  return (
    <MemberDropdown
      value={memberIds}
      onChange={onChange}
      projectId={projectId}
      multiple
      disabled={!isEditable}
      buttonVariant="transparent-with-text"
      button={
        <div className="w-full rounded-sm px-1 py-1 text-left hover:bg-layer-1">
          <PeopleList memberIds={memberIds} />
        </div>
      }
      className="h-auto w-full"
      buttonContainerClassName="-mx-1 h-auto w-full"
    />
  );
}

type TLinkFormProps = {
  initial: TZilBrandLink;
  isSaving: boolean;
  onSubmit: (link: TZilBrandLink) => void;
  onCancel: () => void;
};

function LinkForm({ initial, isSaving, onSubmit, onCancel }: TLinkFormProps) {
  const { t } = useTranslation();
  const [name, setName] = useState(initial.name);
  const [url, setUrl] = useState(initial.url);
  const urlRef = useRef<HTMLInputElement>(null);
  useEffect(() => urlRef.current?.focus(), []);
  const cancelOnEscape = (event: KeyboardEvent<HTMLInputElement>) => event.key === "Escape" && onCancel();

  return (
    <form
      className="flex flex-col gap-1.5 rounded-md border border-subtle bg-layer-1 p-2"
      onSubmit={(event) => {
        event.preventDefault();
        const link = url.trim();
        onSubmit({ name: name.trim(), url: /^https?:\/\//i.test(link) ? link : `https://${link}` });
      }}
    >
      <Input
        ref={urlRef}
        type="text"
        inputMode="url"
        required
        value={url}
        onChange={(event) => setUrl(event.target.value)}
        onKeyDown={cancelOnEscape}
        placeholder="https://drive.google.com/…"
        className="w-full text-13"
        disabled={isSaving}
      />
      <div className="flex items-center gap-1.5">
        <Input
          value={name}
          onChange={(event) => setName(event.target.value)}
          onKeyDown={cancelOnEscape}
          placeholder={t("zil_brand.link_name_placeholder")}
          className="w-full text-13"
          maxLength={120}
          disabled={isSaving}
        />
        <button
          type="submit"
          disabled={isSaving}
          className="flex-shrink-0 rounded-sm p-1 text-tertiary hover:bg-layer-2 hover:text-primary"
          aria-label={t("zil_brand.save_link")}
        >
          <Check className="size-4" />
        </button>
        <button
          type="button"
          disabled={isSaving}
          onClick={onCancel}
          className="flex-shrink-0 rounded-sm p-1 text-tertiary hover:bg-layer-2 hover:text-primary"
          aria-label={t("zil_brand.cancel_link")}
        >
          <X className="size-4" />
        </button>
      </div>
    </form>
  );
}

type TLinksFieldProps = {
  links: TZilBrandLink[];
  isEditable: boolean;
  onSave: (links: TZilBrandLink[]) => Promise<boolean>;
};

/** A list of Drive links (materiales, finales): each opens in a new tab; members add, edit and remove them. */
function LinksField({ links, isEditable, onSave }: TLinksFieldProps) {
  const { t } = useTranslation();
  // the index of the link being edited, "new" while adding one
  const [editing, setEditing] = useState<number | "new" | null>(null);
  const [isSaving, setIsSaving] = useState(false);

  const save = async (next: TZilBrandLink[]) => {
    setIsSaving(true);
    const saved = await onSave(next);
    setIsSaving(false);
    if (saved) setEditing(null);
  };

  return (
    <div className="flex flex-col gap-1">
      {links.length === 0 && editing !== "new" && (
        <span className="py-0.5 text-13 text-placeholder">{t("zil_brand.no_links")}</span>
      )}
      {links.map((link, index) =>
        editing === index ? (
          <LinkForm
            key={`${link.url}|${link.name}`}
            initial={link}
            isSaving={isSaving}
            onSubmit={(edited) => void save(links.map((current, i) => (i === index ? edited : current)))}
            onCancel={() => setEditing(null)}
          />
        ) : (
          <div key={`${link.url}|${link.name}`} className="group flex min-w-0 items-center gap-1.5 rounded-sm py-0.5">
            <a
              href={link.url}
              target="_blank"
              rel="noopener noreferrer"
              className="flex min-w-0 items-center gap-1.5 text-13 text-accent-primary hover:underline"
              title={link.url}
            >
              <FolderOpen className="size-4 flex-shrink-0" />
              <span className="truncate">{link.name || link.url.replace(/^https?:\/\//, "")}</span>
              <ExternalLink className="size-3.5 flex-shrink-0" />
            </a>
            {isEditable && editing === null && (
              <div className="ml-auto flex flex-shrink-0 items-center opacity-0 group-focus-within:opacity-100 group-hover:opacity-100">
                <button
                  type="button"
                  onClick={() => setEditing(index)}
                  className="rounded-sm p-1 text-tertiary hover:bg-layer-1 hover:text-primary"
                  aria-label={t("zil_brand.edit_link")}
                >
                  <Pencil className="size-3.5" />
                </button>
                <button
                  type="button"
                  disabled={isSaving}
                  onClick={() => void save(links.filter((_, i) => i !== index))}
                  className="rounded-sm p-1 text-tertiary hover:bg-layer-1 hover:text-danger-primary"
                  aria-label={t("zil_brand.remove_link")}
                >
                  <Trash2 className="size-3.5" />
                </button>
              </div>
            )}
          </div>
        )
      )}
      {editing === "new" && (
        <LinkForm
          initial={{ name: "", url: "" }}
          isSaving={isSaving}
          onSubmit={(added) => void save([...links, added])}
          onCancel={() => setEditing(null)}
        />
      )}
      {isEditable && editing === null && (
        <button
          type="button"
          onClick={() => setEditing("new")}
          className="mt-1 flex w-fit items-center gap-1 rounded-sm px-1 py-0.5 text-12 text-tertiary hover:bg-layer-1 hover:text-primary"
        >
          <Plus className="size-3.5" />
          {t("zil_brand.add_link")}
        </button>
      )}
    </div>
  );
}

function formatDate(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString();
}

/**
 * The "Marca" tab: who runs the brand and its Drive folders (kept in Ops), then its specifications
 * strip, assets, team and calls, read live from Zil.
 */
export const ZilBrandSheet = observer(function ZilBrandSheet({ workspaceSlug, projectId }: Props) {
  const { t } = useTranslation();
  const { data, isLoading, updateOps } = useZilProjectBrand(workspaceSlug, projectId);
  const { allowPermissions } = useUserPermissions();
  const isEditable = allowPermissions(
    [EUserPermissions.ADMIN, EUserPermissions.MEMBER],
    EUserPermissionsLevel.PROJECT,
    workspaceSlug,
    projectId
  );

  const saveOps = async (changes: Partial<TZilBrandOps>) => {
    try {
      await updateOps(changes);
      return true;
    } catch {
      setToast({ type: TOAST_TYPE.ERROR, title: t("toast.error"), message: t("zil_brand.ops_save_error") });
      return false;
    }
  };

  if (isLoading || !data) {
    return (
      <Loader className="flex flex-col gap-4 p-6">
        <Loader.Item height="56px" width="320px" />
        <Loader.Item height="88px" />
        <Loader.Item height="200px" />
      </Loader>
    );
  }

  const { brand, ops, sheet, unavailable } = data;
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

      <Section title={t("zil_brand.ops_section")}>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <OpsCard label={t("zil_brand.community_manager")}>
            <PeopleField
              projectId={projectId}
              memberIds={ops.community_manager_ids}
              isEditable={isEditable}
              onChange={(memberIds) => void saveOps({ community_manager_ids: memberIds })}
            />
          </OpsCard>
          <OpsCard label={t("zil_brand.leader")}>
            <PeopleField
              projectId={projectId}
              memberIds={ops.leader_ids}
              isEditable={isEditable}
              onChange={(memberIds) => void saveOps({ leader_ids: memberIds })}
            />
          </OpsCard>
          <OpsCard label={t("zil_brand.materials")}>
            <LinksField
              links={ops.materials_links}
              isEditable={isEditable}
              onSave={(links) => saveOps({ materials_links: links })}
            />
          </OpsCard>
          <OpsCard label={t("zil_brand.finals")}>
            <LinksField
              links={ops.finals_links}
              isEditable={isEditable}
              onSave={(links) => saveOps({ finals_links: links })}
            />
          </OpsCard>
        </div>
      </Section>

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

          <Section title={t("zil_brand.files")}>
            {!sheet.files?.length ? (
              <Empty>{t("zil_brand.no_files")}</Empty>
            ) : (
              <ul className="flex flex-col divide-y divide-subtle rounded-md border border-subtle">
                {sheet.files.map((file) => (
                  <li key={file.id} className="flex items-center justify-between gap-3 px-3 py-2">
                    <div className="flex min-w-0 items-center gap-2">
                      <FileText className="size-3.5 flex-shrink-0 text-tertiary" />
                      <span className="truncate text-13 text-primary">{file.name}</span>
                    </div>
                    {file.url && (
                      <a
                        href={file.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="flex-shrink-0 text-tertiary hover:text-primary"
                        aria-label={file.name}
                      >
                        <ExternalLink className="size-4" />
                      </a>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </Section>

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
