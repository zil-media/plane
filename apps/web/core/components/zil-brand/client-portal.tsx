/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { observer } from "mobx-react";
import { Copy, ExternalLink, Mail } from "lucide-react";
// plane imports
import { useTranslation } from "@plane/i18n";
import { Button } from "@plane/propel/button";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import type { TZilPortalClientAccess } from "@plane/types";
import { Loader, ToggleSwitch } from "@plane/ui";
import { copyTextToClipboard } from "@plane/utils";
// hooks
import { useZilProjectPortal } from "@/hooks/use-zil-brands";

type Props = {
  workspaceSlug: string;
  projectId: string;
  isEditable: boolean;
};

const STATUS_KEY: Record<TZilPortalClientAccess["status"], string> = {
  active: "zil_brand.portal_status_active",
  invited: "zil_brand.portal_status_invited",
  expired: "zil_brand.portal_status_expired",
  never: "zil_brand.portal_status_never",
};

/**
 * The brand's client portal: on/off, its link and the client accounts. The accounts come from Zil
 * Workspace (the brand's page invites them), so they are read-only here; only their link is resent.
 */
export const ZilClientPortalSection = observer(function ZilClientPortalSection(props: Props) {
  const { workspaceSlug, projectId, isEditable } = props;
  const { t } = useTranslation();
  const { portal, isLoading, setEnabled, resendInvite } = useZilProjectPortal(workspaceSlug, projectId);
  const [busy, setBusy] = useState<string | null>(null);

  if (isLoading || !portal) return <Loader.Item height="96px" />;

  const run = async (key: string, action: () => Promise<unknown> | undefined, success?: string) => {
    setBusy(key);
    try {
      await action();
      if (success) setToast({ type: TOAST_TYPE.SUCCESS, title: success });
    } catch {
      setToast({ type: TOAST_TYPE.ERROR, title: t("toast.error"), message: t("zil_brand.portal_error") });
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="flex flex-col gap-3 rounded-md border border-subtle p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <ToggleSwitch
            value={portal.enabled}
            disabled={!isEditable || busy === "toggle"}
            onChange={() => void run("toggle", () => setEnabled(!portal.enabled))}
          />
          <span className="text-13 text-primary">
            {portal.enabled ? t("zil_brand.portal_enabled") : t("zil_brand.portal_disabled")}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="secondary"
            size="sm"
            prependIcon={<Copy className="size-3.5" />}
            onClick={() =>
              void copyTextToClipboard(portal.url).then(() =>
                setToast({ type: TOAST_TYPE.SUCCESS, title: t("zil_brand.portal_link_copied") })
              )
            }
          >
            {t("zil_brand.portal_copy_link")}
          </Button>
          {portal.enabled && (
            <a
              href={portal.url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-13 text-accent-primary hover:underline"
            >
              <ExternalLink className="size-3.5" />
              {t("zil_brand.portal_preview")}
            </a>
          )}
        </div>
      </div>
      <p className="text-13 text-tertiary">
        {portal.paused ? t("zil_brand.portal_paused") : t("zil_brand.portal_hint")}
      </p>
      {portal.clients.length === 0 ? (
        <p className="text-13 text-placeholder">{t("zil_brand.portal_no_clients")}</p>
      ) : (
        <ul className="flex flex-col divide-y divide-subtle-1">
          {portal.clients.map((client) => (
            <li key={client.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
              <div className="flex min-w-0 flex-col">
                <span className="truncate text-13 text-primary">{client.email}</span>
                <span className="text-11 text-tertiary">
                  {t(STATUS_KEY[client.status])}
                  {client.last_login &&
                    ` · ${t("zil_brand.portal_last_login")} ${new Date(client.last_login).toLocaleDateString()}`}
                </span>
              </div>
              {isEditable && portal.enabled && !portal.paused && client.has_account && client.status !== "active" && (
                <Button
                  variant="link"
                  size="sm"
                  prependIcon={<Mail className="size-3.5" />}
                  disabled={busy === client.id}
                  onClick={() => void run(client.id, () => resendInvite(client.id), t("zil_brand.portal_resent"))}
                >
                  {t("zil_brand.portal_resend")}
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
});
