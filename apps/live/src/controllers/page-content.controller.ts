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

export const PAGE_CONTENT_ROUTE = "/page-content";

// whole Yjs documents travel in this body, so it gets its own limit (the API caps pages at 10MB)
const parseLargeJSON = express.json({ limit: "25mb" });

const applyPageContentSchema = z
  .object({
    // new content; omitted fields are left untouched
    description_html: z.string().optional(),
    name: z.string().optional(),
    // what the API has stored, used only when the document isn't open on this server
    current_description_binary: z.string().default(""),
    current_description_html: z.string().default("<p></p>"),
    current_name: z.string().default(""),
  })
  .refine((data) => data.description_html !== undefined || data.name !== undefined, {
    message: "description_html or name is required",
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
      // a document still loading gets its stored state merged in after us: wait for it
      const loading = this.hocusPocusServer.loadingDocuments.get(pageId);
      if (loading) await loading;
      const liveDocument = this.hocusPocusServer.documents.get(pageId);

      let yDoc: Y.Doc;
      if (liveDocument) {
        yDoc = liveDocument;
      } else {
        yDoc = new Y.Doc();
        const stored = Buffer.from(body.current_description_binary, "base64");
        // same fallback the database extension uses for pages never opened in the editor
        Y.applyUpdate(
          yDoc,
          stored.byteLength > 0
            ? new Uint8Array(stored)
            : getBinaryDataFromDocumentEditorHTMLString(body.current_description_html, body.current_name)
        );
      }

      // no transaction origin: hocuspocus broadcasts the update to connected editors (and other
      // servers through redis) without running the cookie-authenticated store hooks
      applyHTMLToDocumentEditorYDoc(yDoc, { descriptionHTML: body.description_html, title: body.name });

      const { contentBinaryEncoded, contentHTML, contentJSON } = getAllDocumentFormatsFromDocumentEditorBinaryData(
        Y.encodeStateAsUpdate(yDoc),
        false
      );
      if (!liveDocument) yDoc.destroy();

      return res.status(200).json({
        applied_to_live_document: Boolean(liveDocument),
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
