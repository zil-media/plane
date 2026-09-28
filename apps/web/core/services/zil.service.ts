/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { API_BASE_URL } from "@plane/constants";
// services
import { APIService } from "@/services/api.service";

export type TZilErpLink = {
  type: "Lead" | "MgmtClient" | "TimeProject";
  name: string;
  url: string;
};

/**
 * Zil Workspace (ERP) bridge — read-only lookups for the web app.
 * See apps/api/plane/authentication/views/zil_sync.py (ZilErpLinksEndpoint).
 */
export class ZilService extends APIService {
  constructor() {
    super(API_BASE_URL);
  }

  async getErpLinks(entityType: "project" | "page", entityId: string): Promise<{ links: TZilErpLink[] }> {
    return this.get(`/api/zil/erp-links/`, {
      params: { entity_type: entityType, entity_id: entityId },
    })
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }
}
