/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { Node as PMNode } from "@tiptap/pm/model";
import { updateYFragment, yXmlFragmentToProseMirrorRootNode } from "y-prosemirror";
import type * as Y from "yjs";
import type { EditOp, EditResult } from "./ops";
import { applyEdits } from "./ops";
import { pageSchema } from "./schema";

export const docFromYDoc = (ydoc: Y.Doc): PMNode =>
  yXmlFragmentToProseMirrorRootNode(ydoc.getXmlFragment("default"), pageSchema);

/**
 * Applies the ops to the page body. `updateYFragment` diffs the new document against the Yjs
 * fragment and only rewrites the nodes that differ, so concurrent edits elsewhere survive. The
 * transaction has no origin: on an open document hocuspocus broadcasts it to the connected editors
 * without running the store hooks (the API stores the result).
 */
export const applyEditsToYDoc = (ydoc: Y.Doc, ops: EditOp[]): EditResult => {
  const fragment = ydoc.getXmlFragment("default");
  const result = applyEdits(yXmlFragmentToProseMirrorRootNode(fragment, pageSchema), ops);
  if (result.changed) {
    ydoc.transact(() => updateYFragment(ydoc, fragment, result.doc, { mapping: new Map(), isOMark: new Map() }));
  }
  return result;
};
