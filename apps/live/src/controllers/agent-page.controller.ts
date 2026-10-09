/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { Hocuspocus } from "@hocuspocus/server";
import type { Request, Response } from "express";
import { z } from "zod";
import { Controller, Get, Post } from "@plane/decorators";
import { logger } from "@plane/logger";
import { AppError } from "@/lib/errors";
import { editPageDoc, readPageDoc, renamePageDoc } from "@/lib/page-edit/apply";
import { collectUnits, renderDocument, unitRefs } from "@/lib/page-edit/markdown";
import type { EditOp } from "@/lib/page-edit/ops";
import { PageEditError } from "@/lib/page-edit/ops";
import { APIService } from "@/services/api.service";
import { getPageService } from "@/services/page/handler";
import type { HocusPocusServerContext } from "@/types";

/**
 * Page read/edit for agents (the Ops MCP server). Authenticated with the person's API token
 * (`X-Api-Key`); every call reaches the page through the API-key page routes, so the person's own
 * page permissions apply. Edits are applied to the collaborative document (see lib/page-edit/apply).
 */

type TAgentPage = {
  id: string;
  name: string;
  archived_at: string | null;
  is_locked: boolean;
  is_folder?: boolean;
  can_edit?: boolean;
  access: number;
  updated_at: string;
  parent: string | null;
};

class AgentUserService extends APIService {
  async me(apiKey: string): Promise<{ id: string }> {
    const response = await this.get("/api/v1/users/me/", { headers: { "X-Api-Key": apiKey } });
    return response.data as { id: string };
  }
}

const scopeSchema = z.object({
  workspace_slug: z.string().min(1),
  project_id: z.string().uuid(),
});

const opSchema = z.object({ op: z.string() }).passthrough();
const editSchema = scopeSchema.extend({ ops: z.array(opSchema).min(1).max(100) });
const renameSchema = scopeSchema.extend({ name: z.string().min(1).max(255) });

class HttpError extends Error {
  constructor(
    public status: number,
    message: string
  ) {
    super(message);
  }
}

@Controller("/agent/pages")
export class AgentPageController {
  [key: string]: unknown;
  private readonly hocuspocus: Hocuspocus;

  constructor(hocuspocus: Hocuspocus) {
    this.hocuspocus = hocuspocus;
  }

  private async open(req: Request, scope: z.infer<typeof scopeSchema>, forWrite: boolean) {
    const apiKey = req.header("x-api-key");
    if (!apiKey) throw new HttpError(401, "Missing X-Api-Key.");
    let user: { id: string };
    try {
      user = await new AgentUserService().me(apiKey);
    } catch {
      throw new HttpError(401, "Invalid or expired API token.");
    }
    const context: HocusPocusServerContext = {
      documentType: "project_page",
      workspaceSlug: scope.workspace_slug,
      projectId: scope.project_id,
      userId: user.id,
      cookie: "",
      apiKey,
    };
    const pageId = req.params.pageId;
    let page: TAgentPage;
    try {
      page = (await getPageService("project_page", context).fetchDetails(pageId)) as unknown as TAgentPage;
    } catch (error) {
      const status = new AppError(error).statusCode;
      throw new HttpError(status === 403 || status === 404 ? status : 502, "Page not found or not accessible.");
    }
    if (page.is_folder) throw new HttpError(400, "This is a folder; folders have no content.");
    if (forWrite) {
      if (page.can_edit === false) throw new HttpError(403, "You don't have edit access to this page.");
      if (page.is_locked) throw new HttpError(409, "The page is locked. Unlock it in Ops to edit.");
      if (page.archived_at) throw new HttpError(409, "The page is archived. Restore it to edit.");
    }
    return { context, page, pageId };
  }

  private fail(res: Response, error: unknown, operation: string) {
    if (error instanceof HttpError) return res.status(error.status).json({ error: error.message });
    if (error instanceof PageEditError) return res.status(422).json({ error: error.message });
    if (error instanceof z.ZodError) {
      return res.status(400).json({ error: error.errors.map((e) => `${e.path.join(".")}: ${e.message}`).join("; ") });
    }
    logger.error(`AGENT_PAGE_CONTROLLER: ${operation} failed`, new AppError(error));
    return res.status(500).json({ error: "Internal error while handling the page." });
  }

  @Get("/:pageId")
  async read(req: Request, res: Response) {
    try {
      const scope = scopeSchema.parse(req.query);
      const { context, page, pageId } = await this.open(req, scope, false);
      const doc = await readPageDoc(this.hocuspocus, context, pageId);
      const refs =
        typeof req.query.blocks === "string" && req.query.blocks ? new Set(req.query.blocks.split(",")) : undefined;
      const rendered = renderDocument(doc, {
        offset: Number(req.query.offset ?? 0) || 0,
        limit: Number(req.query.limit ?? 0) || undefined,
        refs,
      });
      res.status(200).json({
        page: {
          id: page.id,
          name: page.name,
          parent_id: page.parent,
          archived_at: page.archived_at,
          is_locked: page.is_locked,
          can_edit: page.can_edit !== false && !page.is_locked && !page.archived_at,
          updated_at: page.updated_at,
        },
        content: rendered.text,
        total_blocks: rendered.total,
        shown_blocks: rendered.shown,
        offset: rendered.offset,
      });
    } catch (error) {
      this.fail(res, error, "read");
    }
  }

  @Post("/:pageId/edit")
  async edit(req: Request, res: Response) {
    try {
      const body = editSchema.parse(req.body);
      const { context, pageId } = await this.open(req, body, true);
      const result = await editPageDoc(this.hocuspocus, context, pageId, body.ops as unknown as EditOp[]);
      // echo the touched blocks so the agent can check the result without re-reading the page
      const units = collectUnits(result.doc);
      const refs = unitRefs(units);
      const touched = new Set<string>();
      units.forEach((unit, index) => {
        if (result.touchedIds.includes(unit.node.attrs.id as string)) touched.add(refs[index]);
      });
      res.status(200).json({
        changed: result.changed,
        summary: result.summary,
        blocks: touched.size ? renderDocument(result.doc, { refs: touched }).text : "",
        total_blocks: units.length,
      });
    } catch (error) {
      this.fail(res, error, "edit");
    }
  }

  @Post("/:pageId/rename")
  async rename(req: Request, res: Response) {
    try {
      const body = renameSchema.parse(req.body);
      const { context, pageId } = await this.open(req, body, true);
      await renamePageDoc(this.hocuspocus, context, pageId, body.name.trim());
      await getPageService("project_page", context).updatePageProperties(pageId, { data: { name: body.name.trim() } });
      res.status(200).json({ id: pageId, name: body.name.trim() });
    } catch (error) {
      this.fail(res, error, "rename");
    }
  }
}
