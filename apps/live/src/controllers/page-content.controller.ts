/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { Hocuspocus } from "@hocuspocus/server";
import express from "express";
import type { Request, Response } from "express";
import * as Y from "yjs";
import { z } from "zod";
// plane imports
import { Controller, Middleware, Post } from "@plane/decorators";
import {
  applyHTMLToDocumentEditorYDoc,
  getAllDocumentFormatsFromDocumentEditorBinaryData,
  getBinaryDataFromDocumentEditorHTMLString,
} from "@plane/editor";
import { logger } from "@plane/logger";
// lib
import { requireSecretKey } from "@/lib/auth-middleware";
import { collectUnits, renderDocument, unitRefs } from "@/lib/page-edit/markdown";
import type { EditOp } from "@/lib/page-edit/ops";
import { PageEditError } from "@/lib/page-edit/ops";
import { applyEditsToYDoc, docFromYDoc } from "@/lib/page-edit/ydoc";

export const PAGE_CONTENT_ROUTE = "/page-content";

// whole Yjs documents travel in this body, so it gets its own limit (the API caps pages at 10MB)
const parseLargeJSON = express.json({ limit: "25mb" });

const applyPageContentSchema = z
  .object({
    // new content; omitted fields are left untouched
    description_html: z.string().optional(),
    name: z.string().optional(),
    current_description_binary: z.string().default(""),
    current_description_html: z.string().default("<p></p>"),
    current_name: z.string().default(""),
  })
  .refine((data) => data.description_html !== undefined || data.name !== undefined, {
    message: "description_html or name is required",
  });

// what the API has stored, used only when the document isn't open on this server
const storedDocumentSchema = z.object({
  current_description_binary: z.string().default(""),
  current_description_html: z.string().default("<p></p>"),
  current_name: z.string().default(""),
});

const editPageSchema = storedDocumentSchema.extend({
  ops: z
    .array(z.object({ op: z.string() }).passthrough())
    .min(1)
    .max(100),
});

const readPageSchema = storedDocumentSchema.extend({
  offset: z.number().int().min(0).default(0),
  limit: z.number().int().min(0).default(0),
  blocks: z.array(z.string()).optional(),
});

/**
 * Server-to-server endpoint used by the API to edit a page outside the editor (public API / agents).
 *
 * The change is applied as a Yjs diff:
 * - on the in-memory document when someone has the page open, so connected editors receive it live
 *   and their later saves already include it (nothing gets clobbered);
 * - otherwise on the stored document, keeping its Yjs history so browsers that cached the page in
 *   IndexedDB merge cleanly instead of duplicating content.
 * The resulting formats are returned for the API to persist.
 */
@Controller(PAGE_CONTENT_ROUTE)
export class PageContentController {
  [key: string]: unknown;
  private readonly hocusPocusServer: Hocuspocus;

  constructor(hocusPocusServer: Hocuspocus) {
    this.hocusPocusServer = hocusPocusServer;
  }

  /** The open document when someone has the page open, else one built from what the API stored. */
  private async pageDocument(
    pageId: string,
    stored: z.infer<typeof storedDocumentSchema>
  ): Promise<{ yDoc: Y.Doc; live: boolean }> {
    // a document still loading gets its stored state merged in after us: wait for it
    const loading = this.hocusPocusServer.loadingDocuments.get(pageId);
    if (loading) await loading;
    const liveDocument = this.hocusPocusServer.documents.get(pageId);
    if (liveDocument) return { yDoc: liveDocument, live: true };
    const yDoc = new Y.Doc();
    const binary = Buffer.from(stored.current_description_binary, "base64");
    // same fallback the database extension uses for pages never opened in the editor
    Y.applyUpdate(
      yDoc,
      binary.byteLength > 0
        ? new Uint8Array(binary)
        : getBinaryDataFromDocumentEditorHTMLString(stored.current_description_html, stored.current_name)
    );
    return { yDoc, live: false };
  }

  /**
   * Block-level edits (agents): replace a phrase, rewrite/insert/delete/move blocks, set attributes.
   * Applied like `apply` (on the open document when there is one) and all-or-nothing: an op that
   * fails changes nothing and answers 422 with the reason. Returns the stored formats to persist
   * and the touched blocks rendered as the agent reads them.
   */
  @Post("/:pageId/edit/")
  @Middleware(parseLargeJSON)
  @Middleware(requireSecretKey)
  async editBlocks(req: Request, res: Response) {
    const pageId = req.params.pageId;
    const parsed = editPageSchema.safeParse(req.body);
    if (!parsed.success) {
      return res.status(400).json({ message: "Validation error", context: parsed.error.flatten() });
    }
    let document: { yDoc: Y.Doc; live: boolean } | undefined;
    try {
      document = await this.pageDocument(pageId, parsed.data);
      const result = applyEditsToYDoc(document.yDoc, parsed.data.ops as unknown as EditOp[]);
      const units = collectUnits(result.doc);
      const refs = unitRefs(units);
      const touched = new Set<string>();
      units.forEach((unit, index) => {
        if (result.touchedIds.includes(unit.node.attrs.id as string)) touched.add(refs[index]);
      });
      const { contentBinaryEncoded, contentHTML, contentJSON } = getAllDocumentFormatsFromDocumentEditorBinaryData(
        Y.encodeStateAsUpdate(document.yDoc),
        false
      );
      return res.status(200).json({
        applied_to_live_document: document.live,
        changed: result.changed,
        summary: result.summary,
        blocks: touched.size ? renderDocument(result.doc, { refs: touched }).text : "",
        total_blocks: units.length,
        description_binary: contentBinaryEncoded,
        description_html: contentHTML,
        description_json: contentJSON,
      });
    } catch (error) {
      if (error instanceof PageEditError) return res.status(422).json({ message: error.message });
      logger.error("PAGE_CONTENT_CONTROLLER: failed to edit blocks", { pageId, error });
      return res.status(500).json({ message: "Internal server error." });
    } finally {
      if (document && !document.live) document.yDoc.destroy();
    }
  }

  /** The page as block-annotated markdown (see lib/page-edit/markdown), from the open document if any. */
  @Post("/:pageId/read/")
  @Middleware(parseLargeJSON)
  @Middleware(requireSecretKey)
  async readBlocks(req: Request, res: Response) {
    const pageId = req.params.pageId;
    const parsed = readPageSchema.safeParse(req.body);
    if (!parsed.success) {
      return res.status(400).json({ message: "Validation error", context: parsed.error.flatten() });
    }
    let document: { yDoc: Y.Doc; live: boolean } | undefined;
    try {
      document = await this.pageDocument(pageId, parsed.data);
      const { offset, limit, blocks } = parsed.data;
      const rendered = renderDocument(docFromYDoc(document.yDoc), {
        offset,
        limit: limit || undefined,
        refs: blocks?.length ? new Set(blocks) : undefined,
      });
      return res.status(200).json({
        content: rendered.text,
        total_blocks: rendered.total,
        shown_blocks: rendered.shown,
        offset: rendered.offset,
      });
    } catch (error) {
      logger.error("PAGE_CONTENT_CONTROLLER: failed to read blocks", { pageId, error });
      return res.status(500).json({ message: "Internal server error." });
    } finally {
      if (document && !document.live) document.yDoc.destroy();
    }
  }

  @Post("/:pageId/apply/")
  // decorators apply bottom-up: the secret key is checked before the body is parsed
  @Middleware(parseLargeJSON)
  @Middleware(requireSecretKey)
  async applyContent(req: Request, res: Response) {
    const pageId = req.params.pageId;
    const parsed = applyPageContentSchema.safeParse(req.body);
    if (!parsed.success) {
      return res.status(400).json({ message: "Validation error", context: parsed.error.flatten() });
    }
    const body = parsed.data;

    try {
      const { yDoc, live } = await this.pageDocument(pageId, body);

      // no transaction origin: hocuspocus broadcasts the update to connected editors (and other
      // servers through redis) without running the cookie-authenticated store hooks
      applyHTMLToDocumentEditorYDoc(yDoc, { descriptionHTML: body.description_html, title: body.name });

      const { contentBinaryEncoded, contentHTML, contentJSON } = getAllDocumentFormatsFromDocumentEditorBinaryData(
        Y.encodeStateAsUpdate(yDoc),
        false
      );
      if (!live) yDoc.destroy();

      return res.status(200).json({
        applied_to_live_document: live,
        description_binary: contentBinaryEncoded,
        description_html: contentHTML,
        description_json: contentJSON,
      });
    } catch (error) {
      logger.error("PAGE_CONTENT_CONTROLLER: failed to apply content", { pageId, error });
      return res.status(500).json({ message: "Internal server error." });
    }
  }
}
