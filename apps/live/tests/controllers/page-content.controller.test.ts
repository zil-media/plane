/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { Document, Hocuspocus } from "@hocuspocus/server";
import type { Request, Response } from "express";
import { beforeAll, describe, expect, it, vi } from "vitest";
import * as Y from "yjs";
import {
  convertBase64StringToBinaryData,
  getAllDocumentFormatsFromDocumentEditorBinaryData,
  getBinaryDataFromDocumentEditorHTMLString,
} from "@plane/editor";

type TController = { applyContent: (req: Request, res: Response) => Promise<unknown> };
type TResult = { status: number; body: Record<string, unknown> };

let PageContentController: new (server: Hocuspocus) => TController;

beforeAll(async () => {
  vi.stubEnv("API_BASE_URL", "http://api.test");
  vi.stubEnv("LIVE_SERVER_SECRET_KEY", "secret");
  ({ PageContentController } = (await import("@/controllers/page-content.controller")) as unknown as {
    PageContentController: typeof PageContentController;
  });
});

const call = async (server: Hocuspocus, pageId: string, body: Record<string, unknown>): Promise<TResult> => {
  const result: TResult = { status: 0, body: {} };
  const res = {
    status(code: number) {
      result.status = code;
      return this;
    },
    json(payload: Record<string, unknown>) {
      result.body = payload;
      return this;
    },
  } as unknown as Response;
  await new PageContentController(server).applyContent({ params: { pageId }, body } as unknown as Request, res);
  return result;
};

const formats = (doc: Y.Doc) => getAllDocumentFormatsFromDocumentEditorBinaryData(Y.encodeStateAsUpdate(doc), true);
// the editor tags its paragraphs with a class; compare structure and text only
const plain = (html: unknown) => String(html).replaceAll(' class="editor-paragraph-block"', "");

const STORED_HTML = "<p>Uno</p><p>Dos</p>";

describe("PageContentController", () => {
  it("merges onto the stored document when the page isn't open", async () => {
    const stored = getBinaryDataFromDocumentEditorHTMLString(STORED_HTML, "Runbook");
    const result = await call(new Hocuspocus(), "page-1", {
      description_html: "<p>Uno</p><p>Dos</p><p>Tres</p>",
      current_description_binary: Buffer.from(stored).toString("base64"),
    });

    expect(result.status).toBe(200);
    expect(result.body.applied_to_live_document).toBe(false);
    expect(plain(result.body.description_html)).toBe("<p>Uno</p><p>Dos</p><p>Tres</p>");

    // a browser that cached the old document in IndexedDB converges without duplicating anything
    const cachedClient = new Y.Doc();
    Y.applyUpdate(cachedClient, stored);
    Y.applyUpdate(cachedClient, convertBase64StringToBinaryData(result.body.description_binary as string));
    expect(plain(formats(cachedClient).contentHTML)).toBe("<p>Uno</p><p>Dos</p><p>Tres</p>");
    expect(formats(cachedClient).titleHTML).toBe("Runbook");
  });

  it("builds the document from the stored HTML when the page was never opened", async () => {
    const result = await call(new Hocuspocus(), "page-2", {
      name: "Nuevo título",
      current_description_html: STORED_HTML,
      current_name: "Viejo",
    });

    expect(result.status).toBe(200);
    expect(plain(result.body.description_html)).toBe(STORED_HTML);
    const doc = new Y.Doc();
    Y.applyUpdate(doc, convertBase64StringToBinaryData(result.body.description_binary as string));
    expect(formats(doc).titleHTML).toBe("Nuevo título");
  });

  it("applies to the open document and keeps concurrent edits of connected editors", async () => {
    const server = new Hocuspocus();
    const liveDocument = new Document("page-3");
    Y.applyUpdate(liveDocument, getBinaryDataFromDocumentEditorHTMLString(STORED_HTML, "Runbook"));
    server.documents.set("page-3", liveDocument);

    // an editor in sync with the server, then typing while the API call happens
    const editor = new Y.Doc();
    Y.applyUpdate(editor, Y.encodeStateAsUpdate(liveDocument));
    const firstParagraph = editor.getXmlFragment("default").get(0) as Y.XmlElement;
    (firstParagraph.get(0) as Y.XmlText).insert(3, " editado");

    const result = await call(server, "page-3", {
      description_html: "<p>Uno</p><p>Dos</p><p>Agregado por el agente</p>",
      // stale stored state must be ignored when the document is open
      current_description_binary: "",
      current_description_html: "<p>viejo</p>",
    });

    expect(result.status).toBe(200);
    expect(result.body.applied_to_live_document).toBe(true);

    Y.applyUpdate(editor, Y.encodeStateAsUpdate(liveDocument));
    Y.applyUpdate(liveDocument, Y.encodeStateAsUpdate(editor));
    const expected = "<p>Uno editado</p><p>Dos</p><p>Agregado por el agente</p>";
    expect(plain(formats(liveDocument).contentHTML)).toBe(expected);
    expect(plain(formats(editor).contentHTML)).toBe(expected);
    expect(formats(liveDocument).titleHTML).toBe("Runbook");
  });

  it("rejects a body with nothing to apply", async () => {
    const result = await call(new Hocuspocus(), "page-4", { current_description_html: STORED_HTML });
    expect(result.status).toBe(400);
  });
});
