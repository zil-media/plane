/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { API_BASE_URL } from "@plane/constants";
import type { TIntake } from "@plane/types";
import { APIService } from "../api.service";

export default class IntakeService extends APIService {
  constructor(BASE_URL?: string) {
    super(BASE_URL || API_BASE_URL);
  }

  /**
   * @description returns the project's (default) Intake — every project has exactly one
   */
  async retrieve(workspaceSlug: string, projectId: string): Promise<TIntake> {
    return this.get(`/api/workspaces/${workspaceSlug}/projects/${projectId}/intakes/`)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }
}

export { IntakeService };
