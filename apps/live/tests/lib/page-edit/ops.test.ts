import { describe, expect, it } from "vitest";
import { renderDocument } from "@/lib/page-edit/markdown";
import { applyEdits, PageEditError } from "@/lib/page-edit/ops";
import { docFromHTML } from "@/lib/page-edit/schema";

const ID = (n: number) => `${String(n).padStart(8, "0")}-0000-4000-8000-000000000000`;

const PAGE = docFromHTML(
  [
    `<h2 data-id="${ID(1)}">Plan</h2>`,
    `<p data-id="${ID(2)}">Hola <strong>equipo</strong>, revisar el presupuesto antes del viernes.</p>`,
    `<ul data-id="${ID(3)}"><li data-id="${ID(4)}"><p>uno</p></li><li data-id="${ID(5)}"><p>dos</p></li></ul>`,
    `<ul data-type="taskList" data-id="${ID(6)}"><li data-type="taskItem" data-checked="false" data-id="${ID(7)}"><p>tarea</p></li></ul>`,
    `<p data-id="${ID(8)}">cierre con presupuesto</p>`,
  ].join("")
);

const lines = (doc = PAGE) =>
  renderDocument(doc)
    .text.split("\n")
    .map((line) => line.replace(/^\S+\s+\| /, ""));

describe("page edit ops", () => {
  it("replaces a phrase and keeps the marks around it", () => {
    const result = applyEdits(PAGE, [{ op: "replace_text", find: "equipo", replace: "team" }]);
    expect(lines(result.doc)[1]).toBe("Hola **team**, revisar el presupuesto antes del viernes.");
    expect(result.touchedIds).toEqual([ID(2)]);
    expect(result.doc.child(0).attrs.id).toBe(ID(1));
  });

  it("requires a unique match unless all or block is given", () => {
    expect(() => applyEdits(PAGE, [{ op: "replace_text", find: "presupuesto", replace: "budget" }])).toThrow(
      /appears 2 times/
    );
    const all = applyEdits(PAGE, [{ op: "replace_text", find: "presupuesto", replace: "budget", all: true }]);
    expect(lines(all.doc).filter((line) => line.includes("budget"))).toHaveLength(2);
    const scoped = applyEdits(PAGE, [
      { op: "replace_text", find: "presupuesto", replace: "budget", block: ID(8).slice(0, 8) },
    ]);
    expect(lines(scoped.doc)[5]).toBe("cierre con budget");
    expect(() => applyEdits(PAGE, [{ op: "replace_text", find: "nada", replace: "x" }])).toThrow(/not found/);
  });

  it("accepts inline markdown in replacements and escaped finds", () => {
    const result = applyEdits(PAGE, [
      { op: "replace_text", find: "viernes", replace: "[viernes](https://zil.global)", markdown: true },
    ]);
    expect(lines(result.doc)[1]).toContain("[viernes](https://zil.global)");
    const escaped = applyEdits(docFromHTML("<p>a*b</p>"), [{ op: "replace_text", find: "a\\*b", replace: "c" }]);
    expect(escaped.doc.textContent).toBe("c");
  });

  it("replaces a block keeping its id", () => {
    const result = applyEdits(PAGE, [{ op: "replace_block", block: ID(2), content: "Nuevo **párrafo**" }]);
    expect(result.doc.child(1).attrs.id).toBe(ID(2));
    expect(lines(result.doc)[1]).toBe("Nuevo **párrafo**");
  });

  it("inserts list items next to an item and blocks outside the list with scope top", () => {
    const items = applyEdits(PAGE, [{ op: "insert", after: ID(4), content: "- uno y medio" }]);
    expect(lines(items.doc).slice(2, 5)).toEqual(["- uno", "- uno y medio", "- dos"]);
    const asItem = applyEdits(PAGE, [{ op: "insert", before: ID(5), content: "texto suelto" }]);
    expect(lines(asItem.doc)[3]).toBe("- texto suelto");
    const outside = applyEdits(PAGE, [{ op: "insert", after: ID(5), scope: "top", content: "## Después" }]);
    expect(lines(outside.doc)[4]).toBe("## Después");
    const ends = applyEdits(PAGE, [
      { op: "insert", at: "start", content: "primero" },
      { op: "insert", at: "end", content: "último" },
    ]);
    expect(lines(ends.doc)[0]).toBe("primero");
    expect(lines(ends.doc).at(-1)).toBe("último");
    expect(new Set(lines(ends.doc)).size).toBe(lines(ends.doc).length);
  });

  it("deletes items, emptied lists and ranges", () => {
    const item = applyEdits(PAGE, [{ op: "delete", block: ID(4) }]);
    expect(lines(item.doc)[2]).toBe("- dos");
    const list = applyEdits(PAGE, [{ op: "delete", block: ID(7) }]);
    expect(list.doc.childCount).toBe(PAGE.childCount - 1);
    const range = applyEdits(PAGE, [{ op: "delete", block: ID(1), through: ID(2) }]);
    expect(lines(range.doc)[0]).toBe("- uno");
    const everything = applyEdits(docFromHTML(`<p data-id="${ID(9)}">solo</p>`), [{ op: "delete", block: ID(9) }]);
    expect(everything.doc.childCount).toBe(1);
    expect(everything.doc.textContent).toBe("");
    expect(() => applyEdits(PAGE, [{ op: "delete", block: ID(2), through: ID(1) }])).toThrow(/later sibling/);
  });

  it("moves blocks and converts items between list types", () => {
    const moved = applyEdits(PAGE, [{ op: "move", block: ID(8), after: ID(1) }]);
    expect(lines(moved.doc)[1]).toBe("cierre con presupuesto");
    const toTask = applyEdits(PAGE, [{ op: "move", block: ID(5), after: ID(7) }]);
    expect(lines(toTask.doc).slice(3, 5)).toEqual(["- [ ] tarea", "- [ ] dos"]);
  });

  it("sets attributes the node actually has", () => {
    const checked = applyEdits(PAGE, [{ op: "set_attrs", block: ID(7), attrs: { checked: true } }]);
    expect(lines(checked.doc)[4]).toBe("- [x] tarea");
    const level = applyEdits(PAGE, [{ op: "set_attrs", block: ID(1), attrs: { level: 1 } }]);
    expect(lines(level.doc)[0]).toBe("# Plan");
    expect(() => applyEdits(PAGE, [{ op: "set_attrs", block: ID(2), attrs: { checked: true } }])).toThrow(
      /has no attribute checked/
    );
  });

  it("keeps ids of unchanged blocks on a full replace", () => {
    const result = applyEdits(PAGE, [
      { op: "replace_all", content: "## Plan\n\notro texto\n\ncierre con presupuesto" },
    ]);
    expect(result.doc.child(0).attrs.id).toBe(ID(1));
    expect(result.doc.child(2).attrs.id).toBe(ID(8));
    expect(result.doc.child(1).attrs.id).not.toBe(ID(2));
  });

  it("is all-or-nothing and reports the failing op", () => {
    const before = PAGE.toJSON();
    expect(() =>
      applyEdits(PAGE, [
        { op: "replace_text", find: "equipo", replace: "team" },
        { op: "delete", block: "ffffffff" },
      ])
    ).toThrow(PageEditError);
    expect(() => applyEdits(PAGE, [{ op: "delete", block: "ffffffff" }])).toThrow(
      /op 1 \(delete\): Block "ffffffff" not found/
    );
    expect(PAGE.toJSON()).toEqual(before);
  });

  it("resolves #n refs against the page as read, giving id-less blocks ids", () => {
    const bare = docFromHTML("<p>a</p><p>b</p><p>c</p>");
    const result = applyEdits(bare, [
      { op: "delete", block: "#1" },
      { op: "replace_text", block: "#3", find: "c", replace: "C" },
    ]);
    expect(result.doc.textContent).toBe("bC");
    result.doc.forEach((node) => expect(node.attrs.id).toMatch(/^[0-9a-f-]{36}$/));
  });

  it("rejects ambiguous and too-short refs", () => {
    const doc = docFromHTML(
      '<p data-id="abcdefgh-1111-4000-8000-000000000001">a</p><p data-id="abcdefgh-2222-4000-8000-000000000002">b</p>'
    );
    expect(() => applyEdits(doc, [{ op: "delete", block: "abcdefgh" }])).toThrow(/ambiguous/);
    expect(() => applyEdits(doc, [{ op: "delete", block: "abc" }])).toThrow(/too short/);
    expect(applyEdits(doc, [{ op: "delete", block: "abcdefgh-222" }]).doc.textContent).toBe("a");
  });
});
