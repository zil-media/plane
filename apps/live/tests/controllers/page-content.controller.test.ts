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

type TController = {
  applyContent: (req: Request, res: Response) => Promise<unknown>;
  editBlocks: (req: Request, res: Response) => Promise<unknown>;
  readBlocks: (req: Request, res: Response) => Promise<unknown>;
};
type TResult = { status: number; body: Record<string, unknown> };

let PageContentController: new (server: Hocuspocus) => TController;

beforeAll(async () => {
  vi.stubEnv("API_BASE_URL", "http://api.test");
  vi.stubEnv("LIVE_SERVER_SECRET_KEY", "secret");
  ({ PageContentController } = (await import("@/controllers/page-content.controller")) as unknown as {
    PageContentController: typeof PageContentController;
  });
});

const call = async (
  server: Hocuspocus,
  pageId: string,
  body: Record<string, unknown>,
  action: "applyContent" | "editBlocks" | "readBlocks" = "applyContent"
): Promise<TResult> => {
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
  await new PageContentController(server)[action]({ params: { pageId }, body } as unknown as Request, res);
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

describe("PageContentController block edits", () => {
  const BLOCKS_HTML =
    '<p data-id="aaaaaaaa-0000-4000-8000-000000000001">Uno</p><p data-id="bbbbbbbb-0000-4000-8000-000000000002">Dos</p>';
  const stored = () =>
    Buffer.from(getBinaryDataFromDocumentEditorHTMLString(BLOCKS_HTML, "Runbook")).toString("base64");

  it("reads the stored page as block-annotated markdown", async () => {
    const result = await call(new Hocuspocus(), "page-5", { current_description_binary: stored() }, "readBlocks");
    expect(result.status).toBe(200);
    expect(result.body.total_blocks).toBe(2);
    expect(String(result.body.content).split("\n")).toHaveLength(2);
  });

  it("edits the stored page and returns what to persist plus the touched blocks", async () => {
    const result = await call(
      new Hocuspocus(),
      "page-6",
      { current_description_binary: stored(), ops: [{ op: "replace_text", find: "Dos", replace: "Dos y medio" }] },
      "editBlocks"
    );
    expect(result.status).toBe(200);
    expect(result.body.changed).toBe(true);
    expect(result.body.applied_to_live_document).toBe(false);
    expect(plain(result.body.description_html)).toContain("Dos y medio");
    expect(String(result.body.blocks)).toContain("Dos y medio");
  });

  it("edits the open document so connected editors receive it and keep their own typing", async () => {
    const server = new Hocuspocus();
    const liveDocument = new Document("page-7");
    Y.applyUpdate(liveDocument, convertBase64StringToBinaryData(stored()));
    server.documents.set("page-7", liveDocument);
    const editor = new Y.Doc();
    Y.applyUpdate(editor, Y.encodeStateAsUpdate(liveDocument));
    const firstParagraph = editor.getXmlFragment("default").get(0) as Y.XmlElement;
    (firstParagraph.get(0) as Y.XmlText).insert(3, " editado");

    const result = await call(
      server,
      "page-7",
      { ops: [{ op: "insert", at: "end", content: "Agregado por el agente" }] },
      "editBlocks"
    );
    expect(result.status).toBe(200);
    expect(result.body.applied_to_live_document).toBe(true);

    Y.applyUpdate(editor, Y.encodeStateAsUpdate(liveDocument));
    Y.applyUpdate(liveDocument, Y.encodeStateAsUpdate(editor));
    for (const doc of [liveDocument, editor]) {
      expect(plain(formats(doc).contentHTML)).toBe("<p>Uno editado</p><p>Dos</p><p>Agregado por el agente</p>");
    }
  });

  it("answers 422 and changes nothing when an op fails", async () => {
    const server = new Hocuspocus();
    const liveDocument = new Document("page-8");
    Y.applyUpdate(liveDocument, convertBase64StringToBinaryData(stored()));
    server.documents.set("page-8", liveDocument);
    const before = Y.encodeStateVector(liveDocument);
    const result = await call(
      server,
      "page-8",
      {
        ops: [
          { op: "replace_text", find: "Uno", replace: "1" },
          { op: "delete", block: "ffffffff" },
        ],
      },
      "editBlocks"
    );
    expect(result.status).toBe(422);
    expect(String(result.body.message)).toContain("op 2 (delete)");
    expect(Y.encodeStateAsUpdate(liveDocument, before).byteLength).toBeLessThanOrEqual(2);
  });
});
