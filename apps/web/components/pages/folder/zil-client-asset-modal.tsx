/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useState } from "react";
// plane imports
import { useTranslation } from "@plane/i18n";
import { Button } from "@makeplane/propel/components/button";
import { Dialog, DialogContent } from "@makeplane/propel/components/dialog";
import { Input } from "@makeplane/propel/components/input";
import { TextArea } from "@makeplane/propel/components/text-area";
import { Select } from "@plane/blocks/select";
import { setToast } from "@plane/blocks/toast";
import type { TZilClientAsset, TZilClientAssetInput, TZilClientAssetKind } from "@plane/types";
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

// Zil refuses longer values with a bare "invalid data" (opsClientSchema assetFields)
const ASSET_LIMITS = { label: 200, url: 2000, externalId: 200, notes: 2000 } as const;

type Props = {
  isOpen: boolean;
  onClose: () => void;
  asset: TZilClientAsset | null;
  workspaceSlug: string;
  projectId: string;
  pageId: string;
  onSaved: (asset: TZilClientAsset) => void;
};

/** What to show for a failed Ops to Zil call: Zil's own sentence, never one of Ops's internal codes. */
export const getZilErrorMessage = (error: unknown): string | undefined => {
  const message = (error as { error?: string } | undefined)?.error;
  return message && !/^[A-Z][A-Z_]+$/.test(message) ? message : undefined;
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
  // a new Drive folder is named after the folder itself; every other case needs a name
  const canSubmit = (isDrive ? !!form.url.trim() : true) && (!!form.label.trim() || (isDrive && !asset));

  const handleSubmit = async () => {
    if (!canSubmit) return;
    setIsSubmitting(true);
    try {
      const { kind, ...fields } = form;
      if (asset) {
        // send only what changed: Zil checks a Drive link as the editor whenever it receives one, so
        // resending the unchanged link would stop anyone without access to the folder from editing its notes
        const changes = Object.fromEntries(
          (Object.keys(fields) as (keyof typeof fields)[])
            .filter((key) => fields[key].trim() !== asset[key])
            .map((key) => [key, fields[key]])
        ) as TZilClientAssetInput;
        if (Object.keys(changes).length === 0) {
          onClose();
          return;
        }
        onSaved(await projectPageService.updateZilClientAsset(workspaceSlug, projectId, pageId, asset.id, changes));
      } else {
        onSaved(await projectPageService.createZilClientAsset(workspaceSlug, projectId, pageId, { kind, ...fields }));
      }
      setToast({ type: "success", title: t("page_tree.zil_client.assets.saved") });
      onClose();
    } catch (error) {
      setToast({
        type: "error",
        title: t("page_tree.zil_client.assets.error"),
        message: getZilErrorMessage(error),
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  const kindOptions = ZIL_ASSET_KINDS.map((kind) => ({
    key: kind,
    label: t(`page_tree.zil_client.assets.kinds.${kind}`),
  }));

  return (
    <Dialog
      open={isOpen}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DialogContent size="lg">
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
            <Select<{ key: TZilClientAssetKind; label: string }>
              getValues={() => kindOptions}
              value={{ key: form.kind, label: t(`page_tree.zil_client.assets.kinds.${form.kind}`) }}
              onChange={(value: string) => set("kind")(value)}
              getOptionValue={(option) => option.key}
              getOptionLabel={(option) => option.label}
              showSearch={false}
              pinSelected={false}
              disabled={!!asset}
              placeholder={t("page_tree.zil_client.assets.kind")}
            >
              <Select.Trigger variant="select-xl" className="w-full">
                <span className="truncate">{t(`page_tree.zil_client.assets.kinds.${form.kind}`)}</span>
              </Select.Trigger>
            </Select>
          </div>

          <div className="flex flex-col gap-1">
            <span className="text-13 text-secondary">{t("page_tree.zil_client.assets.url")}</span>
            <Input
              value={form.url}
              maxLength={ASSET_LIMITS.url}
              onChange={(e) => set("url")(e.target.value)}
              placeholder={isDrive ? "https://drive.google.com/drive/folders/…" : "https://"}
              size="xl"
            />
            {isDrive && <p className="text-11 text-tertiary">{t("page_tree.zil_client.assets.drive_hint")}</p>}
            {form.kind === "vault" && (
              <p className="text-11 text-tertiary">{t("page_tree.zil_client.assets.vault_hint")}</p>
            )}
          </div>

          <div className="flex flex-col gap-1">
            <span className="text-13 text-secondary">{t("page_tree.zil_client.assets.label")}</span>
            <Input
              value={form.label}
              maxLength={ASSET_LIMITS.label}
              onChange={(e) => set("label")(e.target.value)}
              size="xl"
            />
          </div>

          {!isDrive && (
            <div className="flex flex-col gap-1">
              <span className="text-13 text-secondary">{t("page_tree.zil_client.assets.external_id")}</span>
              <Input
                value={form.externalId}
                maxLength={ASSET_LIMITS.externalId}
                onChange={(e) => set("externalId")(e.target.value)}
                size="xl"
              />
            </div>
          )}

          <div className="flex flex-col gap-1">
            <span className="text-13 text-secondary">{t("page_tree.zil_client.assets.notes")}</span>
            <TextArea
              size="lg"
              surface="field"
              rows={4}
              value={form.notes}
              maxLength={ASSET_LIMITS.notes}
              onChange={(e) => set("notes")(e.target.value)}
            />
          </div>

          <div className="flex justify-end gap-2 border-t border-subtle pt-4">
            <Button
              stretch="auto"
              variant="secondary"
              size="lg"
              type="button"
              onClick={onClose}
              label={t("page_tree.zil_client.assets.cancel")}
            />
            <Button
              stretch="auto"
              variant="primary"
              size="lg"
              type="submit"
              loading={isSubmitting}
              disabled={!canSubmit}
              label={t("page_tree.zil_client.assets.save")}
            />
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
