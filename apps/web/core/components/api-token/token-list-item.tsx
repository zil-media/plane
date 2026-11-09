/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { XCircle } from "lucide-react";
// plane imports
import { PROFILE_SETTINGS_TRACKER_ELEMENTS } from "@plane/constants";
import { Tooltip } from "@plane/propel/tooltip";
import type { IApiToken } from "@plane/types";
import { renderFormattedDate, calculateTimeAgo, renderFormattedTime } from "@plane/utils";
// components
import { DeleteApiTokenModal } from "@/components/api-token/delete-token-modal";
// hooks
import { usePlatformOS } from "@/hooks/use-platform-os";

type Props = {
  token: IApiToken;
};

// Zil Ops: a connected app (MCP OAuth) renews its token's expiry on its own, so it never shows as expiring
function statusLabel(token: IApiToken) {
  if (token.is_connector) return token.is_active ? "Connected" : "Disconnected";
  return token.is_active ? "Active" : "Expired";
}

function expiryLabel(token: IApiToken) {
  if (token.is_connector) return "Connected app · renews automatically · delete it to disconnect";
  if (!token.is_active) return `Expired ${calculateTimeAgo(token.expired_at)}`;
  if (!token.expired_at) return "Never expires";
  // a Date, not the ISO string: renderFormattedDate reads a string's UTC day, which is off by one at night
  const expiresAt = new Date(token.expired_at);
  return `Expires ${renderFormattedDate(expiresAt)} at ${renderFormattedTime(expiresAt)}`;
}

export function ApiTokenListItem(props: Props) {
  const { token } = props;
  // states
  const [deleteModalOpen, setDeleteModalOpen] = useState(false);
  // hooks
  const { isMobile } = usePlatformOS();

  return (
    <>
      <DeleteApiTokenModal isOpen={deleteModalOpen} onClose={() => setDeleteModalOpen(false)} tokenId={token.id} />
      <div className="group relative flex flex-col justify-center border-b border-subtle py-3">
        <Tooltip tooltipContent="Delete token" isMobile={isMobile}>
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
            {statusLabel(token)}
          </span>
        </div>
        <div className="mt-1 flex w-full flex-col justify-center">
          {token.description.trim() !== "" && (
            <p className="mb-1 max-w-[70%] text-13 break-words">{token.description}</p>
          )}
          <p className="mb-1 text-11 leading-6 text-placeholder">{expiryLabel(token)}</p>
        </div>
      </div>
    </>
  );
}
