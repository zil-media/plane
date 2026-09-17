/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { Building2 } from "lucide-react";
// plane imports
import { useTranslation } from "@plane/i18n";
import { Tooltip } from "@plane/propel/tooltip";
import type { TPageZilClient } from "@plane/types";
import { cn } from "@plane/utils";

type Props = {
  client: TPageZilClient;
  className?: string;
};

export function ZilClientBadge({ client, className }: Props) {
  const { t } = useTranslation();
  const isMissing = client.lifecycle_status === "missing";
  const label = client.alias || client.company_name;
  const tooltip = isMissing
    ? t("page_tree.zil_client.missing")
    : [client.company_name, client.lifecycle_status].filter(Boolean).join(" · ");

  return (
    <Tooltip tooltipContent={tooltip}>
      <span
        className={cn(
          "inline-flex max-w-48 items-center gap-1 rounded-sm border border-subtle px-1.5 py-0.5 text-11 text-secondary",
          { "border-danger-strong text-danger-secondary": isMissing },
          className
        )}
      >
        <Building2 className="size-3 flex-shrink-0" />
        <span className="truncate">{label}</span>
      </span>
    </Tooltip>
  );
}
