/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { Hocuspocus } from "@hocuspocus/server";
import * as Y from "yjs";
import { getPageService } from "@/services/page/handler";
import type { HocusPocusServerContext } from "@/types";
import type { EditOp, EditResult } from "./ops";
import { applyEdits } from "./ops";
import { docFromHTML } from "./schema";
import { applyEditsToYDoc, docFromYDoc, setTitleInYDoc } from "./ydoc";

/**
 * Agent edits go into the page's Yjs document through Hocuspocus, never as an HTML overwrite: the
 * collaborative doc is the source of truth (the HTML is derived from it on every store), and people
 * with the page open receive the change like any other collaborator's.
 */

/** Current content: the live document when someone has it open, else what the API stored. */
export const readPageDoc = async (hocuspocus: Hocuspocus, context: HocusPocusServerContext, pageId: string) => {
  const loaded = hocuspocus.documents.get(pageId);
  if (loaded) return docFromYDoc(loaded);
  const service = getPageService(context.documentType, context);
  const binary = new Uint8Array(await service.fetchDescriptionBinary(pageId));
  if (binary.byteLength > 0) {
    const ydoc = new Y.Doc();
    Y.applyUpdate(ydoc, binary);
    return docFromYDoc(ydoc);
  }
  const details = await service.fetchDetails(pageId);
  return docFromHTML(details.description_html ?? "<p></p>");
};

/** Runs `change` on the live document and stores it once, the way a collaborator's edit is stored. */
const withLiveDocument = async <T>(
  hocuspocus: Hocuspocus,
  context: HocusPocusServerContext,
  pageId: string,
  change: (ydoc: Y.Doc) => T
): Promise<T> => {
  const connection = await hocuspocus.openDirectConnection(pageId, context);
  try {
    const ydoc = (connection as unknown as { document: Y.Doc }).document;
    return change(ydoc);
  } finally {
    await connection.disconnect();
  }
};

export const editPageDoc = async (
  hocuspocus: Hocuspocus,
  context: HocusPocusServerContext,
  pageId: string,
  ops: EditOp[]
): Promise<EditResult> => {
  // dry run first: an op that fails never opens (and so never re-stores) the live document
  const preview = applyEdits(await readPageDoc(hocuspocus, context, pageId), ops);
  if (!preview.changed) return preview;
  return withLiveDocument(hocuspocus, context, pageId, (ydoc) => applyEditsToYDoc(ydoc, ops));
};

export const renamePageDoc = async (
  hocuspocus: Hocuspocus,
  context: HocusPocusServerContext,
  pageId: string,
  name: string
) => withLiveDocument(hocuspocus, context, pageId, (ydoc) => setTitleInYDoc(ydoc, name));
