/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { getSchema } from "@tiptap/core";
import type { Node as PMNode } from "@tiptap/pm/model";
import { updateYFragment, yXmlFragmentToProseMirrorRootNode } from "y-prosemirror";
import type * as Y from "yjs";
import { TITLE_EDITOR_EXTENSIONS, generateTitleProsemirrorJson } from "@plane/editor";
import type { EditOp, EditResult } from "./ops";
import { applyEdits } from "./ops";
import { pageSchema } from "./schema";

export const PAGE_EDIT_ORIGIN = "agent-page-edit";

const titleSchema = getSchema(TITLE_EDITOR_EXTENSIONS);

const emptyMeta = () => ({ mapping: new Map(), isOMark: new Map() });

export const docFromYDoc = (ydoc: Y.Doc): PMNode =>
  yXmlFragmentToProseMirrorRootNode(ydoc.getXmlFragment("default"), pageSchema);

/**
 * Applies the ops to the page body. `updateYFragment` diffs the new document against the Yjs
 * fragment and only rewrites the nodes that differ, so concurrent edits elsewhere survive.
 */
export const applyEditsToYDoc = (ydoc: Y.Doc, ops: EditOp[]): EditResult => {
  const fragment = ydoc.getXmlFragment("default");
  const result = applyEdits(yXmlFragmentToProseMirrorRootNode(fragment, pageSchema), ops);
  if (result.changed) {
    ydoc.transact(() => updateYFragment(ydoc, fragment, result.doc, emptyMeta()), PAGE_EDIT_ORIGIN);
  }
  return result;
};

/** The editor shows the title from the doc's `title` fragment; TitleSync saves it as the page name. */
export const setTitleInYDoc = (ydoc: Y.Doc, name: string) => {
  const fragment = ydoc.getXmlFragment("title");
  const title = titleSchema.nodeFromJSON(generateTitleProsemirrorJson(name));
  ydoc.transact(() => updateYFragment(ydoc, fragment, title, emptyMeta()), PAGE_EDIT_ORIGIN);
};
