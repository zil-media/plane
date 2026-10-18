/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { API_BASE_URL } from "@plane/constants";
// services
import { APIService } from "@/services/api.service";

/** A project Zil manages: a brand's (Marca) or the workspace's "Migración" one. */
export type TZilBrandProject = {
  project_id: string;
  identifier: string;
  name: string;
  brand_id: string;
  logo_url: string;
  color: string;
  status: "active" | "archived";
  archived: boolean;
  kind: "brand" | "migration";
};

export type TZilBrandSpecItem = { key: string; label: string; value: string; hint?: string | null };

export type TZilBrandSheet = {
  brand: { id: string; name: string; logoUrl: string | null; color: string | null; status: string };
  specs: { strip: TZilBrandSpecItem[]; items: TZilBrandSpecItem[] } | null;
  assets: { id: string; type: string; name: string; url: string | null }[] | null;
  team: { name: string; email: string; role: string | null }[] | null;
  calls:
    | {
        id: string;
        title: string;
        date: string;
        purpose: string | null;
        summary: string | null;
        url: string | null;
      }[]
    | null;
  projects: { workspaceSlug: string; businessUnit: string }[] | null;
};

export type TZilProjectBrand = {
  brand: TZilBrandProject;
  /** null when Zil said no (or the brand has no sheet), and when Zil could not be reached */
  sheet: TZilBrandSheet | null;
  unavailable: boolean;
};

/** The brands (Marcas) a person works on and a brand's live sheet, read from Zil Workspace. */
export class ZilBrandService extends APIService {
  constructor() {
    super(API_BASE_URL);
  }

  async listMyBrands(workspaceSlug: string): Promise<TZilBrandProject[]> {
    return this.get(`/api/workspaces/${workspaceSlug}/zil-brands/`)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async getProjectBrand(workspaceSlug: string, projectId: string): Promise<TZilProjectBrand> {
    return this.get(`/api/workspaces/${workspaceSlug}/projects/${projectId}/zil-brand/`)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }
}
