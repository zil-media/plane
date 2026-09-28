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

export type TZilErpRefKind = "client" | "project";

export type TZilErpOption = { id: string; name: string; subtitle?: string };

export type TZilErpRef = { id: string; name: string; url: string } | null;

export type TZilIssueErpRefs = { client: TZilErpRef; project: TZilErpRef };

export type TZilErpDocTarget = { type: "Lead" | "MgmtClient"; id: string; name: string };

/**
 * Zil Workspace (ERP) bridge for the web app: chips, the work item Cliente/Proyecto properties, and
 * "Guardar en Zil" on work item attachments.
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

  async getErpOptions(workspaceSlug: string, kind: TZilErpRefKind): Promise<{ options: TZilErpOption[] }> {
    return this.get(`/api/zil/erp-options/`, { params: { workspace_slug: workspaceSlug, kind } })
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async getIssueErpRefs(issueId: string): Promise<TZilIssueErpRefs> {
    return this.get(`/api/zil/issue-erp-refs/`, { params: { issue_id: issueId } })
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async setIssueErpRef(issueId: string, kind: TZilErpRefKind, erpId: string | null): Promise<TZilIssueErpRefs> {
    return this.post(`/api/zil/issue-erp-refs/`, { issue_id: issueId, kind, erp_id: erpId })
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async getIssueErpDocTargets(issueId: string): Promise<{ targets: TZilErpDocTarget[] }> {
    return this.get(`/api/zil/issue-erp-targets/`, { params: { issue_id: issueId } })
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async saveIssueAttachmentToZil(issueId: string, assetId: string, target: TZilErpDocTarget): Promise<void> {
    return this.post(`/api/zil/issue-erp-docs/`, {
      issue_id: issueId,
      asset_id: assetId,
      target_type: target.type,
      target_id: target.id,
    })
      .then(() => undefined)
      .catch((error) => {
        throw error?.response?.data;
      });
  }
}
