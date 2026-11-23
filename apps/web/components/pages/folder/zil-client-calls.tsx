/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { ChevronDown, ChevronRight, Phone } from "lucide-react";
// plane imports
import { useTranslation } from "@plane/i18n";
import type { TZilClientProfile } from "@plane/types";
import { renderFormattedDate } from "@plane/utils";

type Props = {
  calls: TZilClientProfile["calls"];
};

export function ZilClientCalls({ calls }: Props) {
  const { t } = useTranslation();
  const [openId, setOpenId] = useState<string | null>(null);

  if (calls.length === 0)
    return (
      <div className="flex flex-col items-center gap-1 rounded-md border border-dashed border-subtle py-12 text-center">
        <Phone className="mb-2 size-8 text-placeholder" />
        <p className="text-13 text-secondary">{t("page_tree.zil_client.calls.empty")}</p>
        <p className="text-11 text-tertiary">{t("page_tree.zil_client.calls.hint")}</p>
      </div>
    );

  return (
    <div className="flex flex-col gap-2">
      <p className="text-11 text-tertiary">{t("page_tree.zil_client.calls.hint")}</p>
      <ul className="flex flex-col divide-y divide-subtle rounded-md border border-subtle">
        {calls.map((call) => {
          const isOpen = openId === call.id;
          return (
            <li key={call.id} className="flex flex-col">
              <button
                type="button"
                onClick={() => setOpenId(isOpen ? null : call.id)}
                className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-layer-transparent-hover"
              >
                {isOpen ? (
                  <ChevronDown className="size-3.5 flex-shrink-0 text-tertiary" />
                ) : (
                  <ChevronRight className="size-3.5 flex-shrink-0 text-tertiary" />
                )}
                <span className="min-w-0 flex-grow truncate text-13 text-primary">{call.title || "—"}</span>
                <span className="flex-shrink-0 rounded-sm border border-subtle px-1.5 py-0.5 text-11 text-secondary">
                  {t(`page_tree.zil_client.calls.purpose.${call.purpose ?? "pending"}`)}
                </span>
                <span className="flex-shrink-0 text-11 text-tertiary">{call.ownerName}</span>
                <span className="flex-shrink-0 text-11 text-tertiary">
                  {t("page_tree.zil_client.calls.minutes", {
                    count: Math.max(1, Math.round(call.durationSeconds / 60)),
                  })}
                </span>
                <span className="w-24 flex-shrink-0 text-right text-11 text-secondary">
                  {renderFormattedDate(call.startedAt)}
                </span>
              </button>
              {isOpen && (
                <div className="px-9 pb-3">
                  {call.summary ? (
                    <p className="text-13 whitespace-pre-wrap text-secondary">{call.summary}</p>
                  ) : (
                    <p className="text-13 text-placeholder">{t("page_tree.zil_client.calls.no_summary")}</p>
                  )}
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
