/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { Extensions, JSONContent } from "@tiptap/core";
import { Extension, getSchema } from "@tiptap/core";
import { generateHTML, generateJSON } from "@tiptap/html";
import type { Node as PMNode } from "@tiptap/pm/model";
import { v4 as uuidv4 } from "uuid";
import { CORE_EXTENSIONS } from "@plane/editor";
import { CoreEditorExtensionsWithoutProps, DocumentEditorExtensionsWithoutProps } from "@plane/editor/lib";

/**
 * Block types that carry a stable `id` attribute in page documents. Mirrors the editor's UniqueID
 * extension (packages/editor/src/core/extensions/unique-id), which is not part of the server-side
 * extension set: without it, converting the Yjs doc to ProseMirror would drop every block id.
 */
export const BLOCK_ID_TYPES: string[] = [
  CORE_EXTENSIONS.PARAGRAPH,
  CORE_EXTENSIONS.HEADING,
  CORE_EXTENSIONS.BLOCKQUOTE,
  CORE_EXTENSIONS.CODE_BLOCK,
  CORE_EXTENSIONS.HORIZONTAL_RULE,
  CORE_EXTENSIONS.BULLET_LIST,
  CORE_EXTENSIONS.ORDERED_LIST,
  CORE_EXTENSIONS.LIST_ITEM,
  CORE_EXTENSIONS.TASK_LIST,
  CORE_EXTENSIONS.TASK_ITEM,
  CORE_EXTENSIONS.TABLE,
  CORE_EXTENSIONS.IMAGE,
  CORE_EXTENSIONS.CUSTOM_IMAGE,
  CORE_EXTENSIONS.CALLOUT,
  CORE_EXTENSIONS.WORK_ITEM_EMBED,
];

const BlockIdExtension = Extension.create({
  name: "pageEditBlockId",
  addGlobalAttributes() {
    return [
      {
        types: BLOCK_ID_TYPES,
        attributes: {
          id: {
            default: null,
            parseHTML: (element) =>
              (element as unknown as { getAttribute: (name: string) => string | null }).getAttribute("data-id"),
            renderHTML: (attributes: Record<string, unknown>) =>
              attributes.id ? { "data-id": attributes.id as string } : {},
          },
        },
      },
    ];
  },
});

export const PAGE_EXTENSIONS: Extensions = [
  ...CoreEditorExtensionsWithoutProps,
  ...DocumentEditorExtensionsWithoutProps,
  BlockIdExtension,
] as Extensions;

export const pageSchema = getSchema(PAGE_EXTENSIONS);

export const LIST_TYPES = new Set<string>([
  CORE_EXTENSIONS.BULLET_LIST,
  CORE_EXTENSIONS.ORDERED_LIST,
  CORE_EXTENSIONS.TASK_LIST,
]);
export const ITEM_TYPES = new Set<string>([CORE_EXTENSIONS.LIST_ITEM, CORE_EXTENSIONS.TASK_ITEM]);

export const canHaveId = (node: PMNode) => BLOCK_ID_TYPES.includes(node.type.name);

export const newBlockId = () => uuidv4();

/** Plane HTML for a fragment of JSON nodes, without the block ids (they are shown separately). */
export const htmlFromJSON = (content: JSONContent[]): string =>
  generateHTML({ type: "doc", content }, PAGE_EXTENSIONS).replace(/\s+data-id="[^"]*"/g, "");

export const docFromHTML = (html: string): PMNode =>
  pageSchema.nodeFromJSON(generateJSON(html || "<p></p>", PAGE_EXTENSIONS));
