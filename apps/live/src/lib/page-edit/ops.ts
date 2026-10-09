/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { JSONContent } from "@tiptap/core";
import type { Node as PMNode, NodeType } from "@tiptap/pm/model";
import { Fragment } from "@tiptap/pm/model";
import { Transform } from "@tiptap/pm/transform";
import { CORE_EXTENSIONS } from "@plane/editor";
import { collectUnits, parseInlineMarkdown, parseMarkdownBlocks, unescapeMarkdown } from "./markdown";
import { BLOCK_ID_TYPES, ITEM_TYPES, LIST_TYPES, canHaveId, newBlockId, pageSchema } from "./schema";

/**
 * Edit operations on a page document. Blocks are addressed by id (or an unambiguous id prefix, as
 * shown in the read gutter) or by `#n` (n-th unit of the document as it was before this edit).
 * All ops of one call apply to one transform: either every op succeeds or nothing changes.
 */

type Ref = string;
type Anchor = { after?: Ref; before?: Ref; at?: "start" | "end"; scope?: "top" };

export type EditOp =
  | { op: "replace_text"; find: string; replace: string; block?: Ref; all?: boolean; markdown?: boolean }
  | { op: "replace_block"; block: Ref; content: string }
  | ({ op: "insert"; content: string } & Anchor)
  | { op: "delete"; block: Ref; through?: Ref }
  | ({ op: "move"; block: Ref } & Anchor)
  | { op: "set_attrs"; block: Ref; attrs: Record<string, unknown> }
  | { op: "replace_all"; content: string };

export class PageEditError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "PageEditError";
  }
}

export type EditResult = { doc: PMNode; changed: boolean; summary: string[]; touchedIds: string[] };

// ─── ids ────────────────────────────────────────────────────────────────────

/** Gives every id-able block an id, and a fresh one to any duplicate. */
const ensureIds = (doc: PMNode, seed?: Set<string>): PMNode => {
  const seen = new Set<string>(seed);
  const walk = (json: JSONContent): JSONContent => {
    if (BLOCK_ID_TYPES.includes(json.type ?? "")) {
      const id = json.attrs?.id as string | undefined;
      if (!id || seen.has(id)) json.attrs = { ...json.attrs, id: newBlockId() };
      seen.add(json.attrs!.id as string);
    }
    if (json.content) json.content = json.content.map(walk);
    return json;
  };
  return pageSchema.nodeFromJSON(walk(doc.toJSON() as JSONContent));
};

const idsIn = (doc: PMNode) => {
  const ids = new Set<string>();
  doc.descendants((node) => {
    if (canHaveId(node) && node.attrs.id) ids.add(node.attrs.id as string);
  });
  return ids;
};

/** Content parsed from markdown with fresh ids that don't collide with the document's. */
const freshBlocks = (doc: PMNode, markdown: string): PMNode[] => {
  const seed = idsIn(doc);
  return parseMarkdownBlocks(markdown).map((node) => {
    const wrapped = ensureIds(pageSchema.node("doc", null, [node]), seed).firstChild!;
    idsIn(pageSchema.node("doc", null, [wrapped])).forEach((id) => seed.add(id));
    return wrapped;
  });
};

// ─── resolution ─────────────────────────────────────────────────────────────

type Located = { node: PMNode; pos: number };

const findById = (doc: PMNode, ref: string): Located => {
  const needle = ref.trim().toLowerCase();
  if (needle.length < 4) throw new PageEditError(`Block ref "${ref}" is too short; use at least 4 characters.`);
  const matches: Located[] = [];
  doc.descendants((node, pos) => {
    const id = node.attrs.id as string | null;
    if (canHaveId(node) && id && id.toLowerCase().startsWith(needle)) matches.push({ node, pos });
  });
  if (matches.length === 0)
    throw new PageEditError(`Block "${ref}" not found. It may have been deleted; read the page again.`);
  const exact = matches.filter(({ node }) => (node.attrs.id as string).toLowerCase() === needle);
  if (exact.length === 1) return exact[0];
  if (matches.length > 1) throw new PageEditError(`Block ref "${ref}" is ambiguous; use more characters of the id.`);
  return matches[0];
};

const parentOf = (doc: PMNode, pos: number) => {
  const $pos = doc.resolve(pos);
  return { parent: $pos.parent, depth: $pos.depth, index: $pos.index() };
};

const topLevelOf = (doc: PMNode, pos: number): Located => {
  const $pos = doc.resolve(pos);
  if ($pos.depth === 0) return { node: doc.nodeAt(pos)!, pos };
  const start = $pos.before(1);
  return { node: doc.nodeAt(start)!, pos: start };
};

// ─── content fitting ────────────────────────────────────────────────────────

const paragraphOf = (node: PMNode) =>
  node.isTextblock && node.type.name !== CORE_EXTENSIONS.CODE_BLOCK
    ? pageSchema.nodes[CORE_EXTENSIONS.PARAGRAPH].create({ id: node.attrs.id ?? newBlockId() }, node.content)
    : null;

/** Turns blocks into list items of `itemType` (lists contribute their items, paragraphs become items). */
const toItems = (blocks: PMNode[], itemType: NodeType): PMNode[] => {
  const items: PMNode[] = [];
  const asItem = (item: PMNode) =>
    item.type === itemType
      ? item
      : itemType.create(
          itemType.name === CORE_EXTENSIONS.TASK_ITEM ? { id: item.attrs.id, checked: false } : { id: item.attrs.id },
          item.content
        );
  for (const block of blocks) {
    if (ITEM_TYPES.has(block.type.name)) {
      items.push(asItem(block));
      continue;
    }
    if (LIST_TYPES.has(block.type.name)) {
      block.forEach((item) => items.push(asItem(item)));
      continue;
    }
    const paragraph = paragraphOf(block);
    if (!paragraph) {
      throw new PageEditError(
        `A ${block.type.name} cannot be a list item on its own. Write it inside an item (indented under a "- " line) or anchor outside the list with scope "top".`
      );
    }
    items.push(itemType.create({ id: newBlockId() }, paragraph));
  }
  return items;
};

/** Fits parsed blocks into the container `target` lives in. */
const fitFor = (target: PMNode, blocks: PMNode[]): PMNode[] =>
  ITEM_TYPES.has(target.type.name) ? toItems(blocks, target.type) : blocks;

// ─── ops ────────────────────────────────────────────────────────────────────

const describe = (node: PMNode) => {
  const text = node.textContent.replace(/\s+/g, " ").trim();
  return `${node.type.name}${text ? ` "${text.length > 40 ? `${text.slice(0, 40)}…` : text}"` : ""}`;
};

const textblocksIn = (doc: PMNode, scope?: Located) => {
  const blocks: Located[] = [];
  const visit = (node: PMNode, pos: number) => {
    if (node.isTextblock) blocks.push({ node, pos });
  };
  if (scope) {
    if (scope.node.isTextblock) visit(scope.node, scope.pos);
    else scope.node.descendants((node, pos) => visit(node, scope.pos + 1 + pos));
  } else doc.descendants(visit);
  return blocks;
};

/** Text of a textblock with each inline non-text node as one placeholder char (positions stay 1:1). */
const flatText = (node: PMNode) => {
  let text = "";
  node.forEach((child) => {
    text += child.isText ? child.text : "￼";
  });
  return text;
};

const replaceText = (tr: Transform, op: Extract<EditOp, { op: "replace_text" }>, touched: Set<string>) => {
  if (!op.find) throw new PageEditError("replace_text needs a non-empty find.");
  if (op.find.includes("\n")) throw new PageEditError("find must sit inside one block (no line breaks).");
  const scope = op.block ? findById(tr.doc, op.block) : undefined;
  const search = (needle: string) => {
    const hits: { from: number; to: number; block: PMNode; blockPos: number }[] = [];
    for (const { node, pos } of textblocksIn(tr.doc, scope)) {
      const text = flatText(node);
      let index = text.indexOf(needle);
      while (index !== -1) {
        hits.push({ from: pos + 1 + index, to: pos + 1 + index + needle.length, block: node, blockPos: pos });
        index = text.indexOf(needle, index + needle.length);
      }
    }
    return hits;
  };
  let hits = search(op.find);
  if (hits.length === 0 && unescapeMarkdown(op.find) !== op.find) hits = search(unescapeMarkdown(op.find));
  if (hits.length === 0) {
    throw new PageEditError(
      `"${op.find}" not found${op.block ? ` in block ${op.block}` : ""}. Match the plain text (no markdown syntax), inside a single block.`
    );
  }
  if (hits.length > 1 && !op.all) {
    throw new PageEditError(
      `"${op.find}" appears ${hits.length} times. Add surrounding words, pass block, or set all: true.`
    );
  }
  const replacement = op.markdown ? parseInlineMarkdown(op.replace) : null;
  for (let index = hits.length - 1; index >= 0; index -= 1) {
    const hit = hits[index];
    if (replacement) tr.replaceWith(hit.from, hit.to, replacement);
    else if (op.replace === "") tr.delete(hit.from, hit.to);
    else tr.replaceWith(hit.from, hit.to, pageSchema.text(op.replace, tr.doc.nodeAt(hit.from)?.marks ?? []));
    const owner = closestIdOwner(tr.doc, tr.mapping.map(hit.blockPos));
    if (owner) touched.add(owner);
  }
  return `replaced ${hits.length} occurrence${hits.length > 1 ? "s" : ""} of "${op.find}"`;
};

/** Id of the nearest unit (top-level block or list item) around a position. */
const closestIdOwner = (doc: PMNode, pos: number): string | null => {
  const $pos = doc.resolve(Math.min(pos + 1, doc.content.size));
  for (let depth = $pos.depth; depth >= 1; depth -= 1) {
    const node = $pos.node(depth);
    if ((depth === 1 || ITEM_TYPES.has(node.type.name)) && node.attrs.id) {
      // prefer the innermost list item, else the top-level block
      if (ITEM_TYPES.has(node.type.name) || depth === 1) return node.attrs.id as string;
    }
  }
  return null;
};

/** Removes a node; an emptied list goes with it, and the doc keeps at least one paragraph. */
const removeRange = (tr: Transform, from: number, to: number) => {
  const $from = tr.doc.resolve(from);
  const parent = $from.parent;
  const removesAll = $from.depth > 0 && from === $from.start() && to === $from.end();
  if (removesAll && LIST_TYPES.has(parent.type.name)) {
    const listPos = $from.before();
    removeRange(tr, listPos, listPos + parent.nodeSize);
    return;
  }
  if (removesAll && ITEM_TYPES.has(parent.type.name)) {
    throw new PageEditError("A list item needs its first paragraph; delete the item instead.");
  }
  tr.delete(from, to);
  if (tr.doc.childCount === 0) {
    tr.insert(0, pageSchema.nodes[CORE_EXTENSIONS.PARAGRAPH].create({ id: newBlockId() }));
  }
};

const insertionPoint = (tr: Transform, anchor: Anchor, opName: string): { pos: number; context: PMNode | null } => {
  const given = [anchor.after, anchor.before, anchor.at].filter((value) => value !== undefined);
  if (given.length !== 1) throw new PageEditError(`${opName} needs exactly one of after, before or at.`);
  if (anchor.at === "start") return { pos: 0, context: null };
  if (anchor.at === "end") return { pos: tr.doc.content.size, context: null };
  if (anchor.at) throw new PageEditError(`at must be "start" or "end".`);
  let target = findById(tr.doc, (anchor.after ?? anchor.before)!);
  if (anchor.scope === "top") target = topLevelOf(tr.doc, target.pos);
  return { pos: anchor.after ? target.pos + target.node.nodeSize : target.pos, context: target.node };
};

const applyOp = (tr: Transform, op: EditOp, touched: Set<string>): string => {
  switch (op.op) {
    case "replace_text":
      return replaceText(tr, op, touched);

    case "replace_block": {
      const target = findById(tr.doc, op.block);
      const blocks = fitFor(target.node, freshBlocks(tr.doc, op.content ?? ""));
      if (blocks.length === 0) throw new PageEditError("replace_block needs content; use delete to remove a block.");
      blocks[0] = blocks[0].type.create(
        { ...blocks[0].attrs, id: target.node.attrs.id },
        blocks[0].content,
        blocks[0].marks
      );
      tr.replaceWith(target.pos, target.pos + target.node.nodeSize, blocks);
      blocks.forEach((block) => touched.add(block.attrs.id as string));
      return `replaced ${describe(target.node)} with ${blocks.length} block${blocks.length > 1 ? "s" : ""}`;
    }

    case "insert": {
      const { pos, context } = insertionPoint(tr, op, "insert");
      const parsed = freshBlocks(tr.doc, op.content ?? "");
      if (parsed.length === 0) throw new PageEditError("insert needs content.");
      const blocks = context ? fitFor(context, parsed) : parsed;
      tr.insert(pos, blocks);
      blocks.forEach((block) => touched.add(block.attrs.id as string));
      return `inserted ${blocks.length} block${blocks.length > 1 ? "s" : ""}`;
    }

    case "delete": {
      const start = findById(tr.doc, op.block);
      let end = start.pos + start.node.nodeSize;
      if (op.through) {
        const last = findById(tr.doc, op.through);
        const a = parentOf(tr.doc, start.pos);
        const b = parentOf(tr.doc, last.pos);
        if (a.parent !== b.parent || a.depth !== b.depth || b.index < a.index) {
          throw new PageEditError("through must be a later sibling of block (same list or top level).");
        }
        end = last.pos + last.node.nodeSize;
      }
      const count = op.through ? parentOf(tr.doc, end - 1).index - parentOf(tr.doc, start.pos).index + 1 : 1;
      removeRange(tr, start.pos, end);
      return `deleted ${count > 1 ? `${count} blocks` : describe(start.node)}`;
    }

    case "move": {
      const source = findById(tr.doc, op.block);
      const node = source.node;
      removeRange(tr, source.pos, source.pos + node.nodeSize);
      const { pos, context } = insertionPoint(tr, op, "move");
      const blocks = context ? fitFor(context, [node]) : ITEM_TYPES.has(node.type.name) ? node.content.content : [node];
      if (!context && ITEM_TYPES.has(node.type.name)) {
        // an item moved to the top level keeps its content as plain blocks
        tr.insert(pos, Fragment.fromArray(blocks.filter((block) => !LIST_TYPES.has(block.type.name))));
      } else tr.insert(pos, blocks);
      touched.add(node.attrs.id as string);
      return `moved ${describe(node)}`;
    }

    case "set_attrs": {
      const target = findById(tr.doc, op.block);
      const allowed = Object.keys(target.node.type.spec.attrs ?? {}).filter((key) => key !== "id");
      const unknown = Object.keys(op.attrs ?? {}).filter((key) => !allowed.includes(key));
      if (unknown.length) {
        throw new PageEditError(
          `${target.node.type.name} has no attribute ${unknown.join(", ")}. Allowed: ${allowed.join(", ") || "none"}.`
        );
      }
      tr.setNodeMarkup(target.pos, undefined, { ...target.node.attrs, ...op.attrs });
      touched.add(target.node.attrs.id as string);
      return `set ${Object.keys(op.attrs).join(", ")} on ${describe(target.node)}`;
    }

    case "replace_all": {
      const blocks = parseMarkdownBlocks(op.content ?? "");
      const next = reuseIds(tr.doc, blocks.length ? blocks : [pageSchema.nodes[CORE_EXTENSIONS.PARAGRAPH].create()]);
      tr.replaceWith(0, tr.doc.content.size, next);
      return `replaced the whole page (${next.length} top-level blocks)`;
    }

    default:
      throw new PageEditError(`Unknown op "${(op as { op: string }).op}".`);
  }
};

const withoutIds = (value: JSONContent): JSONContent => ({
  ...value,
  attrs: value.attrs ? { ...value.attrs, id: null } : undefined,
  content: value.content?.map(withoutIds),
});

/** Keeps the ids of blocks whose content did not change, so a full replace is still a small diff. */
const reuseIds = (doc: PMNode, blocks: PMNode[]): PMNode[] => {
  const key = (node: PMNode) => JSON.stringify(withoutIds(node.toJSON() as JSONContent));
  const pool = new Map<string, PMNode[]>();
  doc.forEach((node) => {
    const list = pool.get(key(node)) ?? [];
    list.push(node);
    pool.set(key(node), list);
  });
  const reused = blocks.map((block) => pool.get(key(block))?.shift() ?? block);
  return [...ensureIds(pageSchema.node("doc", null, reused)).content.content];
};

export const applyEdits = (input: PMNode, ops: EditOp[]): EditResult => {
  if (!Array.isArray(ops) || ops.length === 0) throw new PageEditError("ops must be a non-empty list.");
  // ids first: `#n` refs point at the units of the document as read
  const doc = ensureIds(input);
  const units = collectUnits(doc);
  const resolveIndexRefs = (value: unknown): unknown => {
    if (typeof value !== "string" || !/^#\d+$/.test(value)) return value;
    const unit = units[Number(value.slice(1)) - 1];
    if (!unit) throw new PageEditError(`${value} is out of range (the page has ${units.length} blocks).`);
    return unit.node.attrs.id;
  };

  const tr = new Transform(doc);
  const summary: string[] = [];
  const touched = new Set<string>();
  ops.forEach((raw, index) => {
    const op = { ...raw } as Record<string, unknown>;
    for (const field of ["block", "through", "after", "before"]) op[field] = resolveIndexRefs(op[field]);
    try {
      summary.push(applyOp(tr, op as EditOp, touched));
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      throw new PageEditError(`op ${index + 1} (${String(op.op)}): ${message}`);
    }
  });

  const result = ensureIds(tr.doc);
  try {
    result.check();
  } catch (error) {
    throw new PageEditError(`The edit would produce an invalid page: ${(error as Error).message}`);
  }
  return { doc: result, changed: !result.eq(input), summary, touchedIds: [...touched].filter(Boolean) };
};
