/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useRef, useState } from "react";
import type { ReactNode } from "react";
import {
  AtSign,
  ExternalLink,
  FileImage,
  FileText,
  Folder,
  FolderOpen,
  Globe,
  KeyRound,
  Link2,
  Megaphone,
  Package,
  Pencil,
  Plus,
  ScanLine,
  Trash2,
  Upload,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { sortBy } from "lodash-es";
// plane imports
import { useTranslation } from "@plane/i18n";
import { Button } from "@plane/propel/button";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import { Tooltip } from "@plane/propel/tooltip";
import type { TZilClientAsset, TZilClientAssetKind, TZilClientDriveListing, TZilClientProfile } from "@plane/types";
import { AlertModalCore, Spinner } from "@plane/ui";
import { renderFormattedDate } from "@plane/utils";
// services
import { ProjectPageService } from "@/services/page";
// local imports
import { getZilErrorMessage, ZIL_ASSET_KINDS, ZilClientAssetModal } from "./zil-client-asset-modal";

const projectPageService = new ProjectPageService();

const KIND_ICONS: Record<TZilClientAssetKind, LucideIcon> = {
  drive_folder: FolderOpen,
  ad_account: Megaphone,
  social: AtSign,
  domain: Globe,
  pixel: ScanLine,
  vault: KeyRound,
  link: Link2,
  other: Package,
};

type Props = {
  profile: TZilClientProfile;
  workspaceSlug: string;
  projectId: string;
  pageId: string;
  canEdit: boolean;
  onChange: (update: (profile: TZilClientProfile) => TZilClientProfile) => void;
};

type TDriveState = { status: "loading" } | { status: "ready"; listing: TZilClientDriveListing } | { status: "error" };

type TPendingDelete = { type: "asset"; id: string; name: string } | { type: "file"; id: string; name: string };

function Section({
  title,
  hint,
  action,
  children,
}: {
  title: string;
  hint?: string;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <div className="flex min-w-0 flex-col">
          <h4 className="text-13 font-medium text-tertiary">{title}</h4>
          {hint && <p className="text-11 text-tertiary">{hint}</p>}
        </div>
        {action && <div className="ml-auto">{action}</div>}
      </div>
      {children}
    </section>
  );
}

export function ZilClientAssets(props: Props) {
  const { profile, workspaceSlug, projectId, pageId, canEdit, onChange } = props;
  const { t } = useTranslation();
  // states
  const [editing, setEditing] = useState<TZilClientAsset | null>(null);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<TPendingDelete | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [drive, setDrive] = useState<Record<string, TDriveState>>({});
  const fileInputRef = useRef<HTMLInputElement>(null);
  // derived values
  const kindOrder = (kind: TZilClientAssetKind) => ZIL_ASSET_KINDS.indexOf(kind);
  const assets = sortBy(profile.assets, (asset) => kindOrder(asset.kind));

  const openModal = (asset: TZilClientAsset | null) => {
    setEditing(asset);
    setIsModalOpen(true);
  };

  const handleSaved = (saved: TZilClientAsset) => {
    onChange((current) => ({
      ...current,
      assets: current.assets.some((a) => a.id === saved.id)
        ? current.assets.map((a) => (a.id === saved.id ? saved : a))
        : [...current.assets, saved],
    }));
    // a changed Drive link must be listed again
    setDrive(({ [saved.id]: _stale, ...rest }) => rest);
  };

  const toggleDrive = async (asset: TZilClientAsset) => {
    if (drive[asset.id]) {
      setDrive(({ [asset.id]: _open, ...rest }) => rest);
      return;
    }
    const pending: TDriveState = { status: "loading" };
    setDrive((current) => ({ ...current, [asset.id]: pending }));
    // the answer only counts while this request is still the one shown: hiding the files or editing the
    // link meanwhile drops the entry, and a late answer must not bring back a closed or outdated listing
    const settle = (next: TDriveState) =>
      setDrive((current) => (current[asset.id] === pending ? { ...current, [asset.id]: next } : current));
    try {
      const listing = await projectPageService.getZilClientDriveListing(workspaceSlug, projectId, pageId, asset.id);
      settle({ status: "ready", listing });
    } catch {
      settle({ status: "error" });
    }
  };

  const handleDelete = async () => {
    if (!pendingDelete) return;
    setIsDeleting(true);
    try {
      if (pendingDelete.type === "asset") {
        await projectPageService.deleteZilClientAsset(workspaceSlug, projectId, pageId, pendingDelete.id);
        onChange((current) => ({ ...current, assets: current.assets.filter((a) => a.id !== pendingDelete.id) }));
        setToast({ type: TOAST_TYPE.SUCCESS, title: t("page_tree.zil_client.assets.deleted") });
      } else {
        await projectPageService.deleteZilClientBrandFile(workspaceSlug, projectId, pageId, pendingDelete.id);
        onChange((current) => ({
          ...current,
          brandFiles: current.brandFiles.filter((f) => f.id !== pendingDelete.id),
        }));
        setToast({ type: TOAST_TYPE.SUCCESS, title: t("page_tree.zil_client.assets.file_deleted") });
      }
      setPendingDelete(null);
    } catch (error) {
      setToast({
        type: TOAST_TYPE.ERROR,
        title: t("page_tree.zil_client.assets.delete_error"),
        message: getZilErrorMessage(error),
      });
    } finally {
      setIsDeleting(false);
    }
  };

  const handleUpload = async (file: File | undefined) => {
    if (!file) return;
    setIsUploading(true);
    try {
      const saved = await projectPageService.uploadZilClientBrandFile(workspaceSlug, projectId, pageId, file);
      onChange((current) => ({ ...current, brandFiles: [saved, ...current.brandFiles] }));
      setToast({ type: TOAST_TYPE.SUCCESS, title: t("page_tree.zil_client.assets.uploaded") });
    } catch (error) {
      // 413 comes from the reverse proxy in front of Ops, which answers without a body
      const tooLarge = (error as { status?: number } | undefined)?.status === 413;
      setToast({
        type: TOAST_TYPE.ERROR,
        title: t("page_tree.zil_client.assets.upload_error"),
        message: tooLarge ? t("page_tree.zil_client.assets.upload_too_large") : getZilErrorMessage(error),
      });
    } finally {
      setIsUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const renderDrive = (asset: TZilClientAsset) => {
    const state = drive[asset.id];
    if (!state) return null;
    if (state.status === "loading")
      return (
        <div className="grid h-16 place-items-center">
          <Spinner height="16px" width="16px" />
        </div>
      );
    if (state.status === "error")
      return <p className="px-9 pb-3 text-13 text-secondary">{t("page_tree.zil_client.profile.unavailable")}</p>;
    const { listing } = state;
    if (!listing.ok) return <p className="px-9 pb-3 text-13 text-secondary">{listing.message}</p>;
    if (listing.items.length === 0)
      return <p className="px-9 pb-3 text-13 text-placeholder">{t("page_tree.zil_client.assets.drive_empty")}</p>;
    return (
      <ul className="flex flex-col pb-2">
        {listing.items.map((item) => {
          const Icon = item.isFolder ? Folder : FileText;
          return (
            <li key={item.id}>
              <a
                href={item.url ?? listing.url}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-2 py-1 pr-3 pl-9 text-13 text-secondary hover:bg-layer-transparent-hover hover:text-primary"
              >
                <Icon className="size-3.5 flex-shrink-0 text-tertiary" />
                <span className="min-w-0 flex-grow truncate">{item.name}</span>
                {item.modifiedTime && (
                  <span className="flex-shrink-0 text-11 text-tertiary">{renderFormattedDate(item.modifiedTime)}</span>
                )}
              </a>
            </li>
          );
        })}
        {listing.truncated && (
          <li className="px-9 pt-1 text-11 text-tertiary">{t("page_tree.zil_client.assets.drive_truncated")}</li>
        )}
      </ul>
    );
  };

  return (
    <div className="flex flex-col gap-6">
      <Section
        title={t("page_tree.zil_client.profile.tab_assets")}
        action={
          canEdit && (
            <Button variant="secondary" size="lg" onClick={() => openModal(null)}>
              <Plus className="size-3.5" />
              {t("page_tree.zil_client.assets.add")}
            </Button>
          )
        }
      >
        {assets.length === 0 ? (
          <p className="rounded-md border border-dashed border-subtle px-4 py-6 text-center text-13 text-secondary">
            {t("page_tree.zil_client.assets.empty")}
          </p>
        ) : (
          <ul className="flex flex-col divide-y divide-subtle rounded-md border border-subtle">
            {assets.map((asset) => {
              const Icon = KIND_ICONS[asset.kind] ?? Package;
              const isDrive = asset.kind === "drive_folder";
              return (
                <li key={asset.id} className="group flex flex-col">
                  <div className="flex items-start gap-2 px-3 py-2">
                    <Icon className="mt-0.5 size-3.5 flex-shrink-0 text-tertiary" />
                    <div className="flex min-w-0 flex-grow flex-col">
                      <span className="truncate text-13 text-primary">
                        {asset.label}
                        <span className="text-tertiary"> · {t(`page_tree.zil_client.assets.kinds.${asset.kind}`)}</span>
                      </span>
                      {asset.externalId && <span className="truncate text-11 text-secondary">{asset.externalId}</span>}
                      {asset.notes && <span className="text-11 whitespace-pre-wrap text-secondary">{asset.notes}</span>}
                      <span className="text-11 text-tertiary">
                        {t("page_tree.zil_client.assets.added_by", { name: asset.addedByName || "—" })}
                        {asset.businessUnitSlug && ` · ${asset.businessUnitSlug}`}
                      </span>
                    </div>
                    <div className="flex flex-shrink-0 items-center gap-1">
                      {isDrive && (
                        <Button variant="ghost" size="sm" onClick={() => void toggleDrive(asset)}>
                          {t(
                            drive[asset.id]
                              ? "page_tree.zil_client.assets.drive_hide"
                              : "page_tree.zil_client.assets.drive_show"
                          )}
                        </Button>
                      )}
                      {asset.url && (
                        <Tooltip
                          tooltipContent={t(
                            isDrive ? "page_tree.zil_client.assets.drive_open" : "page_tree.zil_client.assets.open"
                          )}
                        >
                          <a
                            href={asset.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            aria-label={t(
                              isDrive ? "page_tree.zil_client.assets.drive_open" : "page_tree.zil_client.assets.open"
                            )}
                            className="grid size-6 place-items-center rounded-sm text-tertiary hover:bg-layer-transparent-hover hover:text-primary"
                          >
                            <ExternalLink className="size-3.5" />
                          </a>
                        </Tooltip>
                      )}
                      {canEdit && (
                        <>
                          <Tooltip tooltipContent={t("page_tree.zil_client.assets.edit")}>
                            <button
                              type="button"
                              aria-label={t("page_tree.zil_client.assets.edit")}
                              onClick={() => openModal(asset)}
                              className="grid size-6 place-items-center rounded-sm text-tertiary hover:bg-layer-transparent-hover hover:text-primary"
                            >
                              <Pencil className="size-3.5" />
                            </button>
                          </Tooltip>
                          <Tooltip tooltipContent={t("page_tree.zil_client.assets.delete")}>
                            <button
                              type="button"
                              aria-label={t("page_tree.zil_client.assets.delete")}
                              onClick={() => setPendingDelete({ type: "asset", id: asset.id, name: asset.label })}
                              className="grid size-6 place-items-center rounded-sm text-tertiary hover:bg-layer-transparent-hover hover:text-danger-primary"
                            >
                              <Trash2 className="size-3.5" />
                            </button>
                          </Tooltip>
                        </>
                      )}
                    </div>
                  </div>
                  {isDrive && renderDrive(asset)}
                </li>
              );
            })}
          </ul>
        )}
      </Section>

      <Section
        title={t("page_tree.zil_client.assets.brand_files")}
        hint={t("page_tree.zil_client.assets.brand_hint")}
        action={
          canEdit && (
            <>
              <input
                ref={fileInputRef}
                type="file"
                accept="application/pdf,image/png,image/jpeg"
                className="hidden"
                onChange={(e) => void handleUpload(e.target.files?.[0])}
              />
              <Button variant="secondary" size="lg" loading={isUploading} onClick={() => fileInputRef.current?.click()}>
                <Upload className="size-3.5" />
                {t("page_tree.zil_client.assets.upload")}
              </Button>
            </>
          )
        }
      >
        {profile.brandFiles.length === 0 ? (
          <p className="text-13 text-placeholder">{t("page_tree.zil_client.assets.no_brand_files")}</p>
        ) : (
          <ul className="flex flex-col divide-y divide-subtle rounded-md border border-subtle">
            {profile.brandFiles.map((file) => {
              const Icon = file.mimeType.startsWith("image/") ? FileImage : FileText;
              return (
                <li key={file.id} className="flex items-center gap-2 px-3 py-2">
                  <Icon className="size-3.5 flex-shrink-0 text-tertiary" />
                  <a
                    href={projectPageService.zilClientBrandFileHref(workspaceSlug, projectId, pageId, file.id)}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="min-w-0 flex-grow truncate text-13 text-primary hover:underline"
                  >
                    {file.name}
                  </a>
                  <span className="flex-shrink-0 text-11 text-tertiary">
                    {file.uploadedBy}
                    {file.uploadedAt && ` · ${renderFormattedDate(file.uploadedAt)}`}
                  </span>
                  {canEdit && (
                    <Tooltip tooltipContent={t("page_tree.zil_client.assets.delete")}>
                      <button
                        type="button"
                        aria-label={t("page_tree.zil_client.assets.delete")}
                        onClick={() => setPendingDelete({ type: "file", id: file.id, name: file.name })}
                        className="grid size-6 flex-shrink-0 place-items-center rounded-sm text-tertiary hover:bg-layer-transparent-hover hover:text-danger-primary"
                      >
                        <Trash2 className="size-3.5" />
                      </button>
                    </Tooltip>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </Section>

      {profile.adAccounts.length > 0 && (
        <Section
          title={t("page_tree.zil_client.assets.ad_accounts")}
          hint={t("page_tree.zil_client.assets.ad_accounts_hint")}
        >
          <ul className="flex flex-col divide-y divide-subtle rounded-md border border-subtle">
            {profile.adAccounts.map((account) => (
              <li key={`${account.platform}-${account.externalId}`} className="flex items-center gap-2 px-3 py-2">
                <Megaphone className="size-3.5 flex-shrink-0 text-tertiary" />
                <span className="min-w-0 flex-grow truncate text-13 text-primary">{account.name}</span>
                <span className="flex-shrink-0 text-11 text-tertiary">
                  {account.platform === "meta" ? "Meta" : "Google Ads"} · {account.externalId}
                </span>
                {account.businessUnitSlug && (
                  <span className="flex-shrink-0 text-11 text-tertiary">{account.businessUnitSlug}</span>
                )}
              </li>
            ))}
          </ul>
        </Section>
      )}

      <ZilClientAssetModal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        asset={editing}
        workspaceSlug={workspaceSlug}
        projectId={projectId}
        pageId={pageId}
        onSaved={handleSaved}
      />
      <AlertModalCore
        isOpen={!!pendingDelete}
        handleClose={() => setPendingDelete(null)}
        handleSubmit={handleDelete}
        isSubmitting={isDeleting}
        title={t("page_tree.zil_client.assets.delete")}
        content={t("page_tree.zil_client.assets.delete_confirm", { name: pendingDelete?.name ?? "" })}
      />
    </div>
  );
}
