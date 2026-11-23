/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { API_BASE_URL } from "@plane/constants";
import type { AxiosRequestConfig } from "axios";
// services
import { APIService } from "@/services/api.service";

export type TNotionImportJobStatus = "uploaded" | "analyzed" | "processing" | "completed" | "failed";

export type TNotionDatabaseMode = "pages" | "work_items";

export type TNotionManifestPage = {
  title: string;
  path: string;
  parent: string | null;
  database: string | null;
  icon: string | null;
  children: string[];
  assets: string[];
};

export type TNotionManifestDatabase = {
  title: string;
  csv_path: string;
  csv_all_path: string | null;
  parent: string | null;
  columns: string[];
  rows: string[];
};

export type TNotionManifest = {
  version: number;
  source: "notion";
  root_pages: string[];
  pages: Record<string, TNotionManifestPage>;
  databases: Record<string, TNotionManifestDatabase>;
  comment_authors?: string[];
  comment_authors_truncated?: boolean;
  stats: {
    pages: number;
    database_rows: number;
    databases: number;
    assets: number;
  };
};

export type TNotionImportJob = {
  id: string;
  created_at: string;
  updated_at: string;
  source: "notion";
  workspace: string;
  project: string | null;
  status: TNotionImportJobStatus;
  manifest: TNotionManifest;
  config: { databases?: Record<string, TNotionDatabaseMode>; users?: Record<string, string> };
  report: {
    pages_created?: number;
    pages_updated?: number;
    work_items_created?: number;
    work_items_updated?: number;
    comments_created?: number;
    page_comments_skipped?: number;
    assets_uploaded?: number;
    warnings?: string[];
  };
  reason: string;
  initiated_by: string;
};

export class NotionImporterService extends APIService {
  constructor() {
    super(API_BASE_URL);
  }

  async list(workspaceSlug: string): Promise<TNotionImportJob[]> {
    return this.get(`/api/workspaces/${workspaceSlug}/imports/notion/`)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async upload(
    workspaceSlug: string,
    file: File,
    uploadProgressHandler?: AxiosRequestConfig["onUploadProgress"]
  ): Promise<TNotionImportJob> {
    const formData = new FormData();
    formData.append("file", file);
    return this.post(`/api/workspaces/${workspaceSlug}/imports/notion/`, formData, {
      headers: { "Content-Type": "multipart/form-data" },
      onUploadProgress: uploadProgressHandler,
    })
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async retrieve(workspaceSlug: string, jobId: string): Promise<TNotionImportJob> {
    return this.get(`/api/workspaces/${workspaceSlug}/imports/notion/${jobId}/`)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async run(
    workspaceSlug: string,
    jobId: string,
    payload: {
      project_id: string;
      databases: Record<string, TNotionDatabaseMode>;
      users?: Record<string, string>;
    }
  ): Promise<TNotionImportJob> {
    return this.post(`/api/workspaces/${workspaceSlug}/imports/notion/${jobId}/run/`, payload)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async remove(workspaceSlug: string, jobId: string): Promise<void> {
    return this.delete(`/api/workspaces/${workspaceSlug}/imports/notion/${jobId}/`)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }
}
