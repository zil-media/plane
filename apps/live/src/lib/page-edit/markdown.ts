/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { JSONContent } from "@tiptap/core";
import type { Fragment, Mark, Node as PMNode } from "@tiptap/pm/model";
import MarkdownIt from "markdown-it";
import type StateCore from "markdown-it/lib/rules_core/state_core.mjs";
import { CORE_EXTENSIONS } from "@plane/editor";
import { LIST_TYPES, docFromHTML, htmlFromJSON, pageSchema } from "./schema";

/**
 * Pages as markdown for an agent: standard nodes as markdown, anything markdown cannot express
 * (callouts, mentions, images, embeds, colors, alignment) as the editor's own HTML, which parses
 * back to the same node. Every addressable block ("unit") gets a gutter ref the edit ops accept.
 */

// ─── Units ──────────────────────────────────────────────────────────────────

export type Unit = {
  node: PMNode;
  pos: number;
  kind: "block" | "item";
  indent: string;
  marker: string;
};

/** Top-level blocks and every list item (any depth), in reading order. */
export const collectUnits = (doc: PMNode): Unit[] => {
  const units: Unit[] = [];
  const collectList = (list: PMNode, listPos: number, indent: string) => {
    let index = 0;
    list.forEach((item, offset) => {
      const itemPos = listPos + 1 + offset;
      const marker = listMarker(list, item, index);
      units.push({ node: item, pos: itemPos, kind: "item", indent, marker });
      const childIndent = indent + " ".repeat(list.type.name === CORE_EXTENSIONS.ORDERED_LIST ? marker.length : 2);
      item.forEach((child, childOffset) => {
        if (LIST_TYPES.has(child.type.name)) collectList(child, itemPos + 1 + childOffset, childIndent);
      });
      index += 1;
    });
  };
  doc.forEach((node, offset) => {
    if (LIST_TYPES.has(node.type.name)) collectList(node, offset, "");
    else units.push({ node, pos: offset, kind: "block", indent: "", marker: "" });
  });
  return units;
};

const listMarker = (list: PMNode, item: PMNode, index: number) => {
  if (list.type.name === CORE_EXTENSIONS.ORDERED_LIST) return `${((list.attrs.start as number) ?? 1) + index}. `;
  if (list.type.name === CORE_EXTENSIONS.TASK_LIST) return `- [${item.attrs.checked ? "x" : " "}] `;
  return "- ";
};

/** Shortest prefix (min 8) that is unique among the doc's block ids; `#n` for blocks without one. */
export const unitRefs = (units: Unit[]): string[] => {
  const ids = units.map((u) => (u.node.attrs.id as string | null) ?? null);
  const present = ids.filter((id): id is string => !!id);
  return ids.map((id, index) => {
    if (!id) return `#${index + 1}`;
    let length = 8;
    while (length < id.length && present.some((other) => other !== id && other.startsWith(id.slice(0, length)))) {
      length += 4;
    }
    return id.slice(0, length);
  });
};

// ─── Rendering ──────────────────────────────────────────────────────────────

export type RenderOptions = { offset?: number; limit?: number; refs?: Set<string> };

export const renderDocument = (doc: PMNode, options: RenderOptions = {}) => {
  const units = collectUnits(doc);
  const refs = unitRefs(units);
  let selected = units.map((unit, index) => ({ unit, ref: refs[index] }));
  if (options.refs)
    selected = selected.filter(
      ({ ref, unit }) => options.refs!.has(ref) || options.refs!.has(unit.node.attrs.id as string)
    );
  const offset = Math.max(0, options.offset ?? 0);
  const sliced = options.limit ? selected.slice(offset, offset + options.limit) : selected.slice(offset);
  const width = Math.max(8, ...sliced.map(({ ref }) => ref.length));
  const lines: string[] = [];
  for (const { unit, ref } of sliced) {
    renderUnit(unit).forEach((line, index) => {
      lines.push(`${(index === 0 ? ref : "").padEnd(width)} | ${line}`.trimEnd());
    });
  }
  return { text: lines.join("\n"), total: units.length, shown: sliced.length, offset };
};

export const renderUnit = (unit: Unit): string[] => {
  if (unit.kind === "block") return blockMarkdown(unit.node).split("\n");
  const childIndent = unit.indent + " ".repeat(unit.marker.startsWith("- ") ? 2 : unit.marker.length);
  const lines: string[] = [];
  let first = true;
  unit.node.forEach((child) => {
    if (LIST_TYPES.has(child.type.name)) return; // nested items are their own units
    if (first && child.type.name === CORE_EXTENSIONS.PARAGRAPH) {
      lines.push(unit.indent + unit.marker + paragraphText(child));
    } else {
      if (first) lines.push(unit.indent + unit.marker);
      blockMarkdown(child)
        .split("\n")
        .forEach((line) => lines.push(childIndent + line));
    }
    first = false;
  });
  if (first) lines.push(unit.indent + unit.marker);
  return lines;
};

/**
 * Editor HTML for one block. Custom elements (image, work-item embed) get a plain <div> around them:
 * markdown-it only keeps known block tags out of paragraphs, and the editor ignores the wrapper.
 */
const blockHTML = (node: PMNode) => {
  const html = htmlFromJSON([node.toJSON() as JSONContent]);
  return /^<[a-z]+-[a-z-]+[\s>]/.test(html) ? `<div>${html}</div>` : html;
};

/** Alignment, which neither markdown nor the server-side HTML parser keep, as a `{: align=…}` suffix. */
const alignSuffix = (node: PMNode) =>
  node.attrs.textAlign && node.attrs.textAlign !== "left" ? ` {: align=${node.attrs.textAlign as string}}` : "";

const ALIGN_SUFFIX = /\s*\{:\s*align=(left|center|right)\s*\}\s*$/;

const paragraphText = (node: PMNode) => {
  const inline = inlineMarkdown(node.content);
  return inline ?? inlineHTML(node);
};

const inlineHTML = (node: PMNode) =>
  htmlFromJSON([{ type: CORE_EXTENSIONS.PARAGRAPH, content: (node.content.toJSON() as JSONContent[]) ?? [] }])
    .replace(/^<p[^>]*>/, "")
    .replace(/<\/p>$/, "");

export const blockMarkdown = (node: PMNode): string => {
  switch (node.type.name) {
    case CORE_EXTENSIONS.PARAGRAPH: {
      const inline = inlineMarkdown(node.content);
      return inline === null ? blockHTML(node) : escapeLineStart(inline) + alignSuffix(node);
    }
    case CORE_EXTENSIONS.HEADING: {
      const inline = inlineMarkdown(node.content);
      return inline === null
        ? blockHTML(node)
        : `${"#".repeat(node.attrs.level as number)} ${inline}${alignSuffix(node)}`;
    }
    case CORE_EXTENSIONS.CODE_BLOCK: {
      const text = node.textContent;
      const fence = text.includes("```") ? "````" : "```";
      return `${fence}${(node.attrs.language as string) || ""}\n${text}\n${fence}`;
    }
    case CORE_EXTENSIONS.HORIZONTAL_RULE:
      return "---";
    case CORE_EXTENSIONS.BLOCKQUOTE: {
      const parts: string[] = [];
      let simple = true;
      node.forEach((child) => {
        if (![CORE_EXTENSIONS.PARAGRAPH, CORE_EXTENSIONS.HEADING].includes(child.type.name as CORE_EXTENSIONS)) {
          simple = false;
        } else parts.push(blockMarkdown(child));
      });
      if (!simple || parts.some((part) => part.startsWith("<"))) return blockHTML(node);
      return parts
        .join("\n\n")
        .split("\n")
        .map((line) => (line ? `> ${line}` : ">"))
        .join("\n");
    }
    case CORE_EXTENSIONS.TABLE:
      return tableMarkdown(node) ?? blockHTML(node);
    default:
      return blockHTML(node);
  }
};

const tableLine = (cells: string[]) => `| ${cells.join(" | ")} |`;

const tableMarkdown = (table: PMNode): string | null => {
  const rows: string[][] = [];
  let ok = true;
  table.forEach((row, _offset, rowIndex) => {
    const cells: string[] = [];
    row.forEach((cell) => {
      const header = cell.type.name === CORE_EXTENSIONS.TABLE_HEADER;
      if (header !== (rowIndex === 0)) ok = false;
      if ((cell.attrs.colspan as number) > 1 || (cell.attrs.rowspan as number) > 1) ok = false;
      if (cell.childCount !== 1 || cell.firstChild?.type.name !== CORE_EXTENSIONS.PARAGRAPH) ok = false;
      const inline = cell.firstChild ? inlineMarkdown(cell.firstChild.content) : "";
      if (inline === null || inline.includes("<br>") || alignSuffix(cell.firstChild!)) ok = false;
      cells.push((inline ?? "").replace(/\|/g, "\\|"));
    });
    rows.push(cells);
  });
  if (!ok || rows.length === 0) return null;
  return [tableLine(rows[0]), tableLine(rows[0].map(() => "---")), ...rows.slice(1).map(tableLine)].join("\n");
};

// ─── Inline ─────────────────────────────────────────────────────────────────

const MARK_ORDER: string[] = [
  CORE_EXTENSIONS.CUSTOM_LINK,
  CORE_EXTENSIONS.BOLD,
  CORE_EXTENSIONS.ITALIC,
  CORE_EXTENSIONS.STRIKETHROUGH,
  CORE_EXTENSIONS.UNDERLINE,
  CORE_EXTENSIONS.CODE_INLINE,
];

const openMark = (mark: Mark, text: string) => {
  switch (mark.type.name) {
    case CORE_EXTENSIONS.CUSTOM_LINK:
      return "[";
    case CORE_EXTENSIONS.BOLD:
      return "**";
    case CORE_EXTENSIONS.ITALIC:
      return "*";
    case CORE_EXTENSIONS.STRIKETHROUGH:
      return "~~";
    case CORE_EXTENSIONS.UNDERLINE:
      return "<u>";
    default:
      return text.includes("`") ? "`` " : "`";
  }
};

const closeMark = (mark: Mark, text: string) => {
  switch (mark.type.name) {
    case CORE_EXTENSIONS.CUSTOM_LINK: {
      const href = String(mark.attrs.href ?? "");
      return /[\s()<>]/.test(href) ? `](<${href.replace(/[<>]/g, encodeURIComponent)}>)` : `](${href})`;
    }
    case CORE_EXTENSIONS.BOLD:
      return "**";
    case CORE_EXTENSIONS.ITALIC:
      return "*";
    case CORE_EXTENSIONS.STRIKETHROUGH:
      return "~~";
    case CORE_EXTENSIONS.UNDERLINE:
      return "</u>";
    default:
      return text.includes("`") ? " ``" : "`";
  }
};

/** Inline content as markdown, or null when it carries marks markdown cannot express. */
export const inlineMarkdown = (content: Fragment): string | null => {
  let out = "";
  let pending = "";
  const active: Mark[] = [];
  let unsupported = false;
  let codeText = "";

  content.forEach((child) => {
    if (unsupported) return;
    const marks = child.isText ? [...child.marks] : [];
    if (marks.some((mark) => !MARK_ORDER.includes(mark.type.name))) {
      unsupported = true;
      return;
    }
    marks.sort((a, b) => MARK_ORDER.indexOf(a.type.name) - MARK_ORDER.indexOf(b.type.name));
    // close what this node does not continue (stack order)
    while (active.length && !active.every((mark, index) => marks[index]?.eq(mark))) {
      const mark = active.pop()!;
      out += closeMark(mark, codeText);
    }
    out += pending;
    pending = "";
    if (!child.isText) {
      out +=
        child.type.name === CORE_EXTENSIONS.HARD_BREAK
          ? "<br>"
          : inlineHTML(pageSchema.node("paragraph", null, [child]));
      return;
    }
    const text = child.text ?? "";
    const isCode = marks.some((mark) => mark.type.name === CORE_EXTENSIONS.CODE_INLINE);
    const [, lead, core, trail] = isCode
      ? ["", "", text, ""]
      : (/^(\s*)([\s\S]*?)(\s*)$/.exec(text) as RegExpExecArray);
    out += lead;
    for (const mark of marks.slice(active.length)) {
      codeText = text;
      out += openMark(mark, text);
      active.push(mark);
    }
    out += isCode ? core : escapeInline(core);
    pending = trail;
  });
  if (unsupported) return null;
  while (active.length) out += closeMark(active.pop()!, codeText);
  return out + pending;
};

const escapeInline = (text: string) => {
  let out = "";
  for (let i = 0; i < text.length; i += 1) {
    const char = text[i];
    if ("\\`*[]<".includes(char)) out += `\\${char}`;
    else if (char === "~" && text[i + 1] === "~") out += "\\~";
    else if (char === "_" && !(/[\p{L}\p{N}]/u.test(text[i - 1] ?? "") && /[\p{L}\p{N}]/u.test(text[i + 1] ?? "")))
      out += "\\_";
    else if (char === "&" && /^&[#a-zA-Z0-9]+;/.test(text.slice(i))) out += "\\&";
    else out += char;
  }
  return out;
};

const escapeLineStart = (text: string) => {
  if (/^\d+[.)]\s/.test(text)) return text.replace(/^(\d+)([.)])/, "$1\\$2");
  return /^(#{1,6}\s|>|[-+]\s|---)/.test(text) ? `\\${text}` : text;
};

/** Undo the escaping above, so a `find` copied from a read matches the plain text. */
export const unescapeMarkdown = (text: string) => text.replace(/\\([\\`*[\]<~_&#>\-+.|])/g, "$1");

// ─── Parsing ────────────────────────────────────────────────────────────────

/** `- [ ] x` / `- [x] x` lists become the editor's task lists. */
const taskListRule = (state: StateCore) => {
  const tokens = state.tokens;
  for (let i = 0; i < tokens.length; i += 1) {
    if (tokens[i].type !== "bullet_list_open") continue;
    const level = tokens[i].level;
    const items: { li: number; inline: number }[] = [];
    let j = i + 1;
    for (; j < tokens.length && !(tokens[j].type === "bullet_list_close" && tokens[j].level === level); j += 1) {
      if (tokens[j].type === "list_item_open" && tokens[j].level === level + 1) {
        const inline = tokens[j + 2]?.type === "inline" ? j + 2 : -1;
        items.push({ li: j, inline });
      }
    }
    const isTask =
      items.length > 0 && items.every(({ inline }) => inline > 0 && /^\[[ xX]\](\s|$)/.test(tokens[inline].content));
    if (!isTask) continue;
    tokens[i].attrSet("data-type", "taskList");
    for (const { li, inline } of items) {
      const checked = /^\[[xX]\]/.test(tokens[inline].content);
      tokens[li].attrSet("data-type", "taskItem");
      tokens[li].attrSet("data-checked", checked ? "true" : "false");
      tokens[inline].content = tokens[inline].content.replace(/^\[[ xX]\]\s?/, "");
    }
  }
};

const md = new MarkdownIt({ html: true, linkify: false, breaks: false });
// hrefs stay as written (markdown-it would percent-encode spaces and accents)
md.normalizeLink = (url: string) => url;
md.core.ruler.after("block", "plane_task_lists", taskListRule);

/**
 * Post-parse fixes. Alignment comes from the `{: align=…}` suffix. Code blocks: the editor reads the language from a class the server-side DOM does not expose, and
 * markdown-it leaves a trailing newline the editor would keep. Both fixed on the parsed JSON.
 */
const fixParsed = (json: JSONContent, languages: string[]): JSONContent => {
  if (json.type === CORE_EXTENSIONS.CODE_BLOCK) {
    const language = languages.shift();
    if (language) json.attrs = { ...json.attrs, language };
    const last = json.content?.[json.content.length - 1];
    if (json.content && last?.text?.endsWith("\n")) {
      const text = last.text.slice(0, -1);
      json.content = text ? [...json.content.slice(0, -1), { ...last, text }] : json.content.slice(0, -1);
    }
  }
  if (json.type === CORE_EXTENSIONS.PARAGRAPH || json.type === CORE_EXTENSIONS.HEADING) {
    const last = json.content?.[json.content.length - 1];
    const match = last?.type === "text" ? ALIGN_SUFFIX.exec(last.text ?? "") : null;
    if (json.content && last && match) {
      json.attrs = { ...json.attrs, textAlign: match[1] };
      const text = (last.text ?? "").slice(0, match.index);
      json.content = text ? [...json.content.slice(0, -1), { ...last, text }] : json.content.slice(0, -1);
    }
  }
  json.content = json.content?.map((child) => fixParsed(child, languages));
  return json;
};

/** Markdown (with optional editor HTML) → top-level block nodes, without ids. */
export const parseMarkdownBlocks = (markdown: string): PMNode[] => {
  if (!markdown.trim()) return [];
  const tokens = md.parse(markdown, {});
  const languages = tokens
    .filter((token) => token.type === "fence" || token.type === "code_block")
    .map((token) => token.info.trim().split(/\s+/)[0] ?? "");
  const doc = docFromHTML(md.renderer.render(tokens, md.options, {}));
  const json = fixParsed(doc.toJSON() as JSONContent, languages);
  const blocks: PMNode[] = [];
  pageSchema.nodeFromJSON(json).forEach((node) => blocks.push(node));
  return blocks;
};

/** Inline markdown → inline content for a textblock. */
export const parseInlineMarkdown = (markdown: string): Fragment => {
  const doc = docFromHTML(`<p>${md.renderInline(markdown)}</p>`);
  return doc.firstChild!.content;
};
