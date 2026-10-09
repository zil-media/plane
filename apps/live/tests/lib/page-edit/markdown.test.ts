import type { JSONContent } from "@tiptap/core";
import { describe, expect, it } from "vitest";
import { blockMarkdown, parseMarkdownBlocks, renderDocument } from "@/lib/page-edit/markdown";
import { docFromHTML } from "@/lib/page-edit/schema";

const stripIds = (json: JSONContent): JSONContent => ({
  ...json,
  attrs: json.attrs ? Object.fromEntries(Object.entries(json.attrs).filter(([key]) => key !== "id")) : undefined,
  content: json.content?.map(stripIds),
});

/** block → markdown → block gives the same node (ids aside) */
const roundTrips = (html: string) => {
  const original = docFromHTML(html).firstChild!;
  const markdown = blockMarkdown(original);
  const parsed = parseMarkdownBlocks(markdown);
  expect(parsed).toHaveLength(1);
  expect(stripIds(parsed[0].toJSON())).toEqual(stripIds(original.toJSON()));
  return markdown;
};

describe("page markdown", () => {
  it("renders standard blocks as markdown", () => {
    expect(roundTrips("<h2>Título</h2>")).toBe("## Título");
    expect(roundTrips("<p>Hola <strong>mundo</strong>, <em>más</em> y <s>menos</s></p>")).toBe(
      "Hola **mundo**, *más* y ~~menos~~"
    );
    expect(roundTrips('<p>Ver <a href="https://zil.global/a b">el sitio</a> y <code>x()</code></p>')).toBe(
      "Ver [el sitio](<https://zil.global/a b>) y `x()`"
    );
    expect(roundTrips("<p><strong>negrita <em>ambas</em></strong> fin</p>")).toBe("**negrita *ambas*** fin");
    expect(roundTrips("<p>una<br>dos</p>")).toBe("una<br>dos");
    expect(roundTrips("<p><u>subrayado</u></p>")).toBe("<u>subrayado</u>");
    expect(roundTrips("<hr>")).toBe("---");
    expect(roundTrips("<blockquote><p>cita</p></blockquote>")).toBe("> cita");
  });

  it("keeps plain text plain and escapes only markdown syntax", () => {
    expect(roundTrips("<p>snake_case y a*b y [x] y &lt;tag&gt;</p>")).toBe("snake_case y a\\*b y \\[x\\] y \\<tag>");
    expect(roundTrips("<p># no es título</p>")).toBe("\\# no es título");
    expect(roundTrips("<p>1. no es lista</p>")).toBe("1\\. no es lista");
  });

  it("renders code blocks with their language", () => {
    const [code] = parseMarkdownBlocks("```ts\nconst a = 1;\nconst b = 2;\n```");
    expect(code.attrs.language).toBe("ts");
    expect(code.textContent).toBe("const a = 1;\nconst b = 2;");
    expect(blockMarkdown(code)).toBe("```ts\nconst a = 1;\nconst b = 2;\n```");
  });

  it("renders simple tables as GFM and round-trips them", () => {
    const markdown = roundTrips(
      "<table><tbody><tr><th><p>A</p></th><th><p>B</p></th></tr><tr><td><p>1</p></td><td><p>a | b</p></td></tr></tbody></table>"
    );
    expect(markdown).toBe("| A | B |\n| --- | --- |\n| 1 | a \\| b |");
  });

  it("falls back to editor HTML for nodes markdown cannot express, and parses it back", () => {
    roundTrips(
      '<div data-block-type="callout-component" data-logo-in-use="emoji" data-emoji-unicode="128161"><p>ojo</p></div>'
    );
    const mention = roundTrips(
      '<p>Hola <mention-component id="m1" entity_identifier="11111111-1111-1111-1111-111111111111" entity_name="user_mention"></mention-component></p>'
    );
    expect(mention).toContain("<mention-component");
    roundTrips('<image-component src="22222222-2222-2222-2222-222222222222" width="300px"></image-component>');
    expect(roundTrips('<image-component src="33333333-3333-3333-3333-333333333333"></image-component>')).toMatch(
      /^<div><image-component/
    );
  });

  it("keeps alignment as a suffix", () => {
    const [aligned] = parseMarkdownBlocks("centrado {: align=center}");
    expect(aligned.attrs.textAlign).toBe("center");
    expect(aligned.textContent).toBe("centrado");
    expect(blockMarkdown(aligned)).toBe("centrado {: align=center}");
    const [heading] = parseMarkdownBlocks("## Título {: align=right}");
    expect(heading.attrs).toMatchObject({ level: 2, textAlign: "right" });
  });

  it("parses task lists", () => {
    const [list] = parseMarkdownBlocks("- [ ] pendiente\n- [x] hecho");
    expect(list.type.name).toBe("taskList");
    expect(list.child(0).attrs.checked).toBe(false);
    expect(list.child(1).attrs.checked).toBe(true);
    expect(list.child(1).textContent).toBe("hecho");
  });

  it("gives every top-level block and list item its own gutter ref", () => {
    const doc = docFromHTML(
      '<h1 data-id="aaaaaaaa-0000-4000-8000-000000000001">T</h1><ul data-id="aaaaaaaa-0000-4000-8000-000000000002"><li data-id="bbbbbbbb-0000-4000-8000-000000000003"><p>uno</p><ul><li><p>anidado</p></li></ul></li></ul><ul data-type="taskList"><li data-type="taskItem" data-checked="true"><p>hecho</p></li></ul>'
    );
    const { text, total } = renderDocument(doc);
    expect(total).toBe(4);
    expect(text.split("\n")).toEqual([
      "aaaaaaaa | # T",
      "bbbbbbbb | - uno",
      "#3       |   - anidado",
      "#4       | - [x] hecho",
    ]);
    expect(renderDocument(doc, { offset: 1, limit: 2 }).text.split("\n")).toHaveLength(2);
  });

  it("lengthens refs when ids share a prefix", () => {
    const doc = docFromHTML(
      '<p data-id="abcdefgh-1111-4000-8000-000000000001">a</p><p data-id="abcdefgh-2222-4000-8000-000000000002">b</p>'
    );
    expect(renderDocument(doc).text).toBe("abcdefgh-111 | a\nabcdefgh-222 | b");
  });
});
