/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import useSWR from "swr";
// plane imports
import { NewTabIcon } from "@plane/propel/icons";
// services
import { ZilService } from "@/services/zil.service";
import type { TZilErpLink } from "@/services/zil.service";

const zilService = new ZilService();

type Props = {
  entityType: "project" | "page";
  entityId: string | undefined;
};

/**
 * Pill linking a Plane project/page back to the Zil Workspace (ERP) entities
 * that reference it. Renders nothing when the entity isn't linked or the ERP
 * is unreachable — purely decorative. Styling mirrors the "Public" pill in the
 * work-items header; issues get the same affordance natively via their Links.
 */
export const ZilLinkChip = ({ entityType, entityId }: Props) => {
  const shouldFetch = !!entityId;
  const { data } = useSWR(
    shouldFetch ? `ZIL_ERP_LINKS_${entityType}_${entityId}` : null,
    shouldFetch ? () => zilService.getErpLinks(entityType, entityId ?? "") : null,
    { revalidateOnFocus: false, shouldRetryOnError: false }
  );

  if (!data?.links?.length) return null;

  return (
    <>
      {data.links.map((link: TZilErpLink) => (
        <a
          key={`${link.type}-${link.name}-${link.url}`}
          href={link.url}
          target="_blank"
          rel="noopener noreferrer"
          className="group flex flex-shrink-0 items-center gap-1.5 rounded-sm bg-accent-primary/10 px-2.5 py-1 text-11 font-medium text-accent-primary"
        >
          Zil · {link.name}
          <NewTabIcon className="hidden h-3 w-3 group-hover:block" strokeWidth={2} />
        </a>
      ))}
    </>
  );
};
