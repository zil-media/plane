/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { XCircle } from "lucide-react";
// plane imports
import { PROFILE_SETTINGS_TRACKER_ELEMENTS } from "@plane/constants";
import { useTranslation } from "@plane/i18n";
import { Tooltip } from "@plane/propel/tooltip";
import type { IApiToken } from "@plane/types";
import { renderFormattedDate, renderFormattedTime } from "@plane/utils";
// components
import { DeleteApiTokenModal } from "@/components/api-token/delete-token-modal";
// hooks
import { usePlatformOS } from "@/hooks/use-platform-os";

type Props = {
  token: IApiToken;
};

type TFunction = ReturnType<typeof useTranslation>["t"];

// Zil Ops: a connected app (MCP OAuth) renews its token's expiry on its own, so it never shows as expiring
function statusLabel(token: IApiToken, t: TFunction) {
  if (token.is_connector) {
    return t(
      token.is_active
        ? "account_settings.api_tokens.status.connected"
        : "account_settings.api_tokens.status.disconnected"
    );
  }
  return t(
    token.is_active ? "account_settings.api_tokens.status.active" : "account_settings.api_tokens.status.expired"
  );
}

function expiryLabel(token: IApiToken, t: TFunction) {
  if (token.is_connector) return t("account_settings.api_tokens.expiry.connector");
  if (!token.expired_at) return t("account_settings.api_tokens.expiry.never");
  // a Date, not the ISO string: renderFormattedDate reads a string's UTC day, which is off by one at night
  const expiresAt = new Date(token.expired_at);
  if (!token.is_active)
    return t("account_settings.api_tokens.expiry.expired", { date: renderFormattedDate(expiresAt) });
  return t("account_settings.api_tokens.expiry.expires", {
    date: renderFormattedDate(expiresAt),
    time: renderFormattedTime(expiresAt),
  });
}

export function ApiTokenListItem(props: Props) {
  const { token } = props;
  // states
  const [deleteModalOpen, setDeleteModalOpen] = useState(false);
  // hooks
  const { isMobile } = usePlatformOS();
  const { t } = useTranslation();

  return (
    <>
      <DeleteApiTokenModal isOpen={deleteModalOpen} onClose={() => setDeleteModalOpen(false)} tokenId={token.id} />
      <div className="group relative flex flex-col justify-center border-b border-subtle py-3">
        <Tooltip tooltipContent={t("account_settings.api_tokens.delete")} isMobile={isMobile}>
          <button
            onClick={() => setDeleteModalOpen(true)}
            className="absolute right-4 hidden place-items-center group-hover:grid"
            data-ph-element={PROFILE_SETTINGS_TRACKER_ELEMENTS.LIST_ITEM_DELETE_ICON}
          >
            <XCircle className="h-4 w-4 text-danger-primary" />
          </button>
        </Tooltip>
        <div className="flex w-4/5 items-center">
          <h5 className="truncate text-13 font-medium">{token.label}</h5>
          <span
            className={`${
              token.is_active ? "bg-success-subtle text-success-primary" : "bg-layer-1 text-placeholder"
            } ml-2 flex h-4 max-h-fit items-center rounded-xs px-2 text-11 font-medium`}
          >
            {statusLabel(token, t)}
          </span>
        </div>
        <div className="mt-1 flex w-full flex-col justify-center">
          {token.description.trim() !== "" && (
            <p className="mb-1 max-w-[70%] text-13 break-words">{token.description}</p>
          )}
          <p className="mb-1 text-11 leading-6 text-placeholder">{expiryLabel(token, t)}</p>
        </div>
      </div>
    </>
  );
}
