import { prosemirrorToYXmlFragment } from "y-prosemirror";
import { describe, expect, it } from "vitest";
import * as Y from "yjs";
import { docFromHTML } from "@/lib/page-edit/schema";
import { applyEditsToYDoc, docFromYDoc } from "@/lib/page-edit/ydoc";

const ID = (n: number) => `${String(n).padStart(8, "0")}-0000-4000-8000-000000000000`;

const pageYDoc = (html: string) => {
  const ydoc = new Y.Doc();
  prosemirrorToYXmlFragment(docFromHTML(html), ydoc.getXmlFragment("default"));
  return ydoc;
};

const sync = (a: Y.Doc, b: Y.Doc) => {
  Y.applyUpdate(b, Y.encodeStateAsUpdate(a, Y.encodeStateVector(b)));
  Y.applyUpdate(a, Y.encodeStateAsUpdate(b, Y.encodeStateVector(a)));
};

describe("page edits on the Yjs document", () => {
  it("merges with a concurrent edit from someone with the page open", () => {
    const server = pageYDoc(`<p data-id="${ID(1)}">primer párrafo</p><p data-id="${ID(2)}">segundo párrafo</p>`);
    const browser = new Y.Doc();
    sync(server, browser);

    // the person types in paragraph 2 while the agent edits paragraph 1
    applyEditsToYDoc(browser, [{ op: "replace_text", find: "segundo", replace: "SEGUNDO (persona)" }]);
    applyEditsToYDoc(server, [{ op: "replace_text", find: "primer", replace: "PRIMER (agente)" }]);
    sync(server, browser);

    for (const doc of [server, browser]) {
      expect(docFromYDoc(doc).textContent).toBe("PRIMER (agente) párrafoSEGUNDO (persona) párrafo");
    }
  });

  it("sends a small update, not the whole page", () => {
    const html = Array.from(
      { length: 200 },
      (_, i) => `<p data-id="${ID(i + 1)}">párrafo número ${i + 1} con algo de texto</p>`
    ).join("");
    const ydoc = pageYDoc(html);
    const before = Y.encodeStateVector(ydoc);
    applyEditsToYDoc(ydoc, [{ op: "replace_text", find: "número 150 ", replace: "número 150 (editado) " }]);
    const update = Y.encodeStateAsUpdate(ydoc, before);
    expect(update.byteLength).toBeLessThan(Y.encodeStateAsUpdate(ydoc).byteLength / 20);
  });

  it("keeps block ids in the stored document", () => {
    const ydoc = pageYDoc(`<p data-id="${ID(1)}">a</p>`);
    applyEditsToYDoc(ydoc, [{ op: "insert", after: ID(1), content: "b" }]);
    const doc = docFromYDoc(ydoc);
    expect(doc.child(0).attrs.id).toBe(ID(1));
    expect(doc.child(1).attrs.id).toMatch(/^[0-9a-f-]{36}$/);
  });

  it("does not touch the document when nothing changes", () => {
    const ydoc = pageYDoc(`<p data-id="${ID(1)}">a</p>`);
    const before = Y.encodeStateVector(ydoc);
    const result = applyEditsToYDoc(ydoc, [{ op: "replace_text", find: "a", replace: "a" }]);
    expect(result.changed).toBe(false);
    expect(Y.encodeStateAsUpdate(ydoc, before).byteLength).toBeLessThanOrEqual(2);
  });
});
