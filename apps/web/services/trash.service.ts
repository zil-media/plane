/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { API_BASE_URL } from "@plane/constants";
// services
import { APIService } from "@/services/api.service";

export type TTrashItemType = "issue" | "page" | "cycle" | "module" | "project";

export type TTrashItem = {
  id: string;
  type: TTrashItemType;
  name: string;
  sequence_id: number | null;
  project_identifier: string | null;
  deleted_at: string;
  deleted_by_name: string | null;
  days_remaining: number;
};

export class TrashService extends APIService {
  constructor() {
    super(API_BASE_URL);
  }

  async list(workspaceSlug: string, projectId: string, type: TTrashItemType): Promise<TTrashItem[]> {
    const url =
      type === "project"
        ? `/api/workspaces/${workspaceSlug}/trash/projects/`
        : `/api/workspaces/${workspaceSlug}/projects/${projectId}/trash/`;
    return this.get(url, { params: type === "project" ? undefined : { type } })
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async restore(workspaceSlug: string, projectId: string, type: TTrashItemType, itemId: string): Promise<void> {
    const url =
      type === "project"
        ? `/api/workspaces/${workspaceSlug}/trash/projects/${itemId}/restore/`
        : `/api/workspaces/${workspaceSlug}/projects/${projectId}/trash/${type}/${itemId}/restore/`;
    return this.post(url)
      .then(() => undefined)
      .catch((error) => {
        throw error?.response?.data;
      });
  }
}

export const trashService = new TrashService();
