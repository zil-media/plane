/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useState } from "react";
// plane imports
import { useTranslation } from "@plane/i18n";
import { Button } from "@plane/propel/button";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import type { TZilClientAsset, TZilClientAssetInput, TZilClientAssetKind } from "@plane/types";
import { CustomSelect, EModalPosition, EModalWidth, Input, ModalCore, TextArea } from "@plane/ui";
// services
import { ProjectPageService } from "@/services/page";

const projectPageService = new ProjectPageService();

export const ZIL_ASSET_KINDS: TZilClientAssetKind[] = [
  "drive_folder",
  "ad_account",
  "social",
  "domain",
  "pixel",
  "vault",
  "link",
  "other",
];

type Props = {
  isOpen: boolean;
  onClose: () => void;
  asset: TZilClientAsset | null;
  workspaceSlug: string;
  projectId: string;
  pageId: string;
  onSaved: (asset: TZilClientAsset) => void;
};

const emptyForm = (): Required<TZilClientAssetInput> => ({
  kind: "drive_folder",
  label: "",
  url: "",
  externalId: "",
  notes: "",
});

export function ZilClientAssetModal(props: Props) {
  const { isOpen, onClose, asset, workspaceSlug, projectId, pageId, onSaved } = props;
  const { t } = useTranslation();
  const [form, setForm] = useState<Required<TZilClientAssetInput>>(emptyForm);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const isDrive = form.kind === "drive_folder";

  useEffect(() => {
    if (!isOpen) return;
    setForm(
      asset
        ? { kind: asset.kind, label: asset.label, url: asset.url, externalId: asset.externalId, notes: asset.notes }
        : emptyForm()
    );
  }, [isOpen, asset]);

  const set = (key: keyof TZilClientAssetInput) => (value: string) =>
    setForm((current) => ({ ...current, [key]: value }));
  const canSubmit = isDrive ? !!form.url.trim() : !!form.label.trim();

  const handleSubmit = async () => {
    if (!canSubmit) return;
    setIsSubmitting(true);
    try {
      const { kind, ...fields } = form;
      const saved = asset
        ? await projectPageService.updateZilClientAsset(workspaceSlug, projectId, pageId, asset.id, fields)
        : await projectPageService.createZilClientAsset(workspaceSlug, projectId, pageId, { kind, ...fields });
      onSaved(saved);
      setToast({ type: TOAST_TYPE.SUCCESS, title: t("page_tree.zil_client.assets.saved") });
      onClose();
    } catch (error) {
      const message = (error as { error?: string } | undefined)?.error;
      setToast({
        type: TOAST_TYPE.ERROR,
        title: t("page_tree.zil_client.assets.error"),
        message: message && message !== "ZIL_UNAVAILABLE" ? message : undefined,
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <ModalCore isOpen={isOpen} handleClose={onClose} position={EModalPosition.TOP} width={EModalWidth.XL}>
      <form
        className="flex flex-col gap-4 p-5"
        onSubmit={(e) => {
          e.preventDefault();
          void handleSubmit();
        }}
      >
        <h3 className="text-16 font-medium text-primary">
          {t(asset ? "page_tree.zil_client.assets.edit" : "page_tree.zil_client.assets.add")}
        </h3>

        <div className="flex flex-col gap-1">
          <span className="text-13 text-secondary">{t("page_tree.zil_client.assets.kind")}</span>
          <CustomSelect
            value={form.kind}
            label={<span>{t(`page_tree.zil_client.assets.kinds.${form.kind}`)}</span>}
            onChange={(value: TZilClientAssetKind) => set("kind")(value)}
            disabled={!!asset}
            maxHeight="lg"
            buttonClassName="w-full rounded-md border border-subtle px-3 py-2 text-13"
            input
          >
            {ZIL_ASSET_KINDS.map((kind) => (
              <CustomSelect.Option key={kind} value={kind}>
                {t(`page_tree.zil_client.assets.kinds.${kind}`)}
              </CustomSelect.Option>
            ))}
          </CustomSelect>
        </div>

        <div className="flex flex-col gap-1">
          <span className="text-13 text-secondary">{t("page_tree.zil_client.assets.url")}</span>
          <Input
            value={form.url}
            onChange={(e) => set("url")(e.target.value)}
            placeholder={isDrive ? "https://drive.google.com/drive/folders/…" : "https://"}
            className="w-full"
            inputSize="md"
          />
          {isDrive && <p className="text-11 text-tertiary">{t("page_tree.zil_client.assets.drive_hint")}</p>}
          {form.kind === "vault" && (
            <p className="text-11 text-tertiary">{t("page_tree.zil_client.assets.vault_hint")}</p>
          )}
        </div>

        <div className="flex flex-col gap-1">
          <span className="text-13 text-secondary">{t("page_tree.zil_client.assets.label")}</span>
          <Input value={form.label} onChange={(e) => set("label")(e.target.value)} className="w-full" inputSize="md" />
        </div>

        {!isDrive && (
          <div className="flex flex-col gap-1">
            <span className="text-13 text-secondary">{t("page_tree.zil_client.assets.external_id")}</span>
            <Input
              value={form.externalId}
              onChange={(e) => set("externalId")(e.target.value)}
              className="w-full"
              inputSize="md"
            />
          </div>
        )}

        <div className="flex flex-col gap-1">
          <span className="text-13 text-secondary">{t("page_tree.zil_client.assets.notes")}</span>
          <TextArea
            value={form.notes}
            onChange={(e) => set("notes")(e.target.value)}
            className="min-h-20 w-full text-13"
          />
        </div>

        <div className="flex justify-end gap-2 border-t border-subtle pt-4">
          <Button variant="secondary" size="lg" type="button" onClick={onClose}>
            {t("page_tree.zil_client.assets.cancel")}
          </Button>
          <Button variant="primary" size="lg" type="submit" loading={isSubmitting} disabled={!canSubmit}>
            {t("page_tree.zil_client.assets.save")}
          </Button>
        </div>
      </form>
    </ModalCore>
  );
}
