/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { API_BASE_URL } from "@plane/constants";
// services
import { APIService } from "@/services/api.service";

export type TZilClientStatesState = { name: string; color: string; group: string };

export type TZilClientStatesProject = { id: string; name: string; states: TZilClientStatesState[] };

export type TZilClientStatesPreview = { clients: number; work_items_to_move: number };

export type TZilClientStates = {
  template_project_id: string | null;
  applied_at: string | null;
  projects: TZilClientStatesProject[];
  preview: TZilClientStatesPreview | null;
};

export type TZilClientStatesResult = {
  template_project_id: string;
  result: { clients: number; updated: number; work_items_moved: number; failed: string[] } | null;
};

export class ZilClientStatesService extends APIService {
  constructor() {
    super(API_BASE_URL);
  }

  async fetchSettings(workspaceSlug: string, templateProjectId?: string): Promise<TZilClientStates> {
    return this.get(
      `/api/workspaces/${workspaceSlug}/zil-client-states/`,
      templateProjectId ? { params: { template_project_id: templateProjectId } } : {}
    )
      .then((response) => response?.data as TZilClientStates)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async apply(workspaceSlug: string, templateProjectId: string): Promise<TZilClientStatesResult> {
    return this.put(`/api/workspaces/${workspaceSlug}/zil-client-states/`, {
      template_project_id: templateProjectId,
      apply: true,
    })
      .then((response) => response?.data as TZilClientStatesResult)
      .catch((error) => {
        throw error?.response?.data;
      });
  }
}

export const zilClientStatesService = new ZilClientStatesService();
