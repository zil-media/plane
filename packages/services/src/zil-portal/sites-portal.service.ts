/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// plane imports
import { API_BASE_URL } from "@plane/constants";
import type {
  TZilPortalBrand,
  TZilPortalComment,
  TZilPortalDocument,
  TZilPortalDraft,
  TZilPortalFolder,
  TZilPortalInvite,
  TZilPortalPost,
  TZilPortalPostDetail,
  TZilPortalReview,
} from "@plane/types";
// api service
import { APIService } from "../api.service";

/**
 * A brand's client portal (/api/public/portal/): the brands of the signed-in client, their
 * calendar, posts, comments and documents, and the invitation link.
 * @remarks Only for the sites (space) app.
 */
export class SitesPortalService extends APIService {
  constructor(BASE_URL?: string) {
    super(BASE_URL || API_BASE_URL);
  }

  private async read<T>(request: Promise<{ data: T }>): Promise<T> {
    return request
      .then((response) => response?.data)
      .catch((error) => {
        // a network failure has no response: still an error the screens can show
        throw error?.response ?? { status: 0 };
      });
  }

  async brands(): Promise<{ brands: TZilPortalBrand[] }> {
    return this.read(this.get("/api/public/portal/"));
  }

  async brand(projectId: string): Promise<TZilPortalBrand> {
    return this.read(this.get(`/api/public/portal/${projectId}/`));
  }

  async posts(
    projectId: string,
    range: { start: string; end: string }
  ): Promise<{ posts: TZilPortalPost[]; to_review: TZilPortalPost[] }> {
    return this.read(this.get(`/api/public/portal/${projectId}/posts/`, { params: range }));
  }

  async retrievePost(projectId: string, postId: string): Promise<TZilPortalPostDetail> {
    return this.read(this.get(`/api/public/portal/${projectId}/posts/${postId}/`));
  }

  async comments(projectId: string, postId: string): Promise<{ comments: TZilPortalComment[] }> {
    return this.read(this.get(`/api/public/portal/${projectId}/posts/${postId}/comments/`));
  }

  /** The changes the client is writing on a post (theirs only, not sent yet). */
  async drafts(projectId: string, postId: string): Promise<{ drafts: TZilPortalDraft[] }> {
    return this.read(this.get(`/api/public/portal/${projectId}/posts/${postId}/drafts/`));
  }

  async addDraft(
    projectId: string,
    postId: string,
    text: string,
    moment?: { media: string; at: number }
  ): Promise<TZilPortalDraft> {
    return this.read(this.post(`/api/public/portal/${projectId}/posts/${postId}/drafts/`, { text, ...moment }));
  }

  async updateDraft(projectId: string, postId: string, draftId: string, text: string): Promise<TZilPortalDraft> {
    return this.read(this.patch(`/api/public/portal/${projectId}/posts/${postId}/drafts/${draftId}/`, { text }));
  }

  async deleteDraft(projectId: string, postId: string, draftId: string): Promise<void> {
    return this.read(this.delete(`/api/public/portal/${projectId}/posts/${postId}/drafts/${draftId}/`));
  }

  /** Send the client's drafts to the team as one round of changes (after they confirmed). */
  async sendChanges(
    projectId: string,
    postId: string
  ): Promise<{ comments: TZilPortalComment[]; review: TZilPortalReview }> {
    return this.read(this.post(`/api/public/portal/${projectId}/posts/${postId}/send-changes/`, { confirm: true }));
  }

  async documents(projectId: string): Promise<{ folders: TZilPortalFolder[]; documents: TZilPortalDocument[] }> {
    return this.read(this.get(`/api/public/portal/${projectId}/documents/`));
  }

  async document(projectId: string, documentId: string): Promise<TZilPortalDocument> {
    return this.read(this.get(`/api/public/portal/${projectId}/documents/${documentId}/`));
  }

  async documentComments(projectId: string, documentId: string): Promise<{ comments: TZilPortalComment[] }> {
    return this.read(this.get(`/api/public/portal/${projectId}/documents/${documentId}/comments/`));
  }

  async addDocumentComment(projectId: string, documentId: string, text: string): Promise<TZilPortalComment> {
    return this.read(this.post(`/api/public/portal/${projectId}/documents/${documentId}/comments/`, { text }));
  }

  async invite(token: string): Promise<TZilPortalInvite> {
    return this.read(this.get(`/api/public/portal/invite/${token}/`));
  }

  /** `sign_in`: the account already has its own password, so it signs in with it (no session made here). */
  async acceptInvite(token: string, password: string): Promise<{ project_id: string; sign_in?: boolean }> {
    return this.read(this.post(`/api/public/portal/invite/${token}/`, { password }));
  }
}
