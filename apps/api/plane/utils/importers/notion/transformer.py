# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
Transforms Notion export HTML into Plane editor-compatible HTML.

The output vocabulary follows ``plane/utils/content_validator.py`` (the
canonical allowlist for stored ``description_html``) and the TipTap
extensions in ``packages/editor``:

- images        -> ``<image-component src="notion-asset://<zip path>">``
                   (the import task uploads the asset and swaps the src
                   for the FileAsset id)
- internal link -> ``href="notion-page://<uuid>"`` (swapped for the real
                   page URL once every page exists)
- database view -> ``<div data-notion-database="<uuid>"></div>`` marker
                   (replaced according to the per-database import mode)
- highlights    -> ``<span data-text-color|data-background-color="key">``
- callouts      -> Plane callout component ``div``
- columns       -> flattened sequentially (no columns in the editor)
- toggles       -> bold paragraph followed by the revealed content
"""

import posixpath
import re
from dataclasses import dataclass, field
from urllib.parse import unquote, urlparse

from bs4 import BeautifulSoup, NavigableString, Tag

FILENAME_UUID_RE = re.compile(r" ([0-9a-f]{32})\.html$")

# Notion highlight color -> Plane editor color key (COLORS_LIST)
NOTION_COLOR_MAP = {
    "gray": "gray",
    "brown": "orange",
    "orange": "orange",
    "yellow": "peach",
    "teal": "green",
    "green": "green",
    "blue": "light-blue",
    "purple": "purple",
    "pink": "pink",
    "red": "peach",
    "default": None,
}

INLINE_KEEP_TAGS = {"strong", "em", "u", "s", "del", "code", "br", "sup", "sub"}
BLOCK_PASSTHROUGH_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "hr"}

ASSET_SCHEME = "notion-asset://"
PAGE_SCHEME = "notion-page://"


@dataclass
class TransformResult:
    html: str
    asset_paths: list = field(default_factory=list)  # zip entry paths referenced
    page_refs: list = field(default_factory=list)  # notion uuids referenced by links
    database_refs: list = field(default_factory=list)  # embedded database uuids
    comments: list = field(default_factory=list)  # [{"id", "author", "html"}]
    warnings: list = field(default_factory=list)


def extract_comment_authors(html_content):
    """Return the distinct comment author names found in an exported page."""
    transformer = NotionHTMLTransformer(page_path="")
    transformer._result = TransformResult(html="")
    if isinstance(html_content, bytes):
        html_content = html_content.decode("utf-8", errors="replace")
    transformer._extract_comments(BeautifulSoup(html_content, "html.parser"))
    return {comment["author"] for comment in transformer._result.comments if comment["author"]}


class NotionHTMLTransformer:
    """Transforms one exported Notion page into Plane editor HTML."""

    def __init__(self, page_path, known_assets=None):
        # directory of the page inside the zip — relative srcs resolve here
        self._base_dir = posixpath.dirname(page_path)
        # optional set of valid asset entry paths (to verify references)
        self._known_assets = known_assets
        self._result = None

    def transform(self, html_content):
        if isinstance(html_content, bytes):
            html_content = html_content.decode("utf-8", errors="replace")
        self._result = TransformResult(html="")
        soup = BeautifulSoup(html_content, "html.parser")
        self._extract_comments(soup)
        body = soup.find("div", class_="page-body") or soup.find("article") or soup

        out = BeautifulSoup("", "html.parser")
        for child in list(body.children):
            for node in self._transform_block(child, out):
                out.append(node)

        self._merge_adjacent_lists(out)
        html = str(out).strip() or "<p></p>"
        self._result.html = html
        return self._result

    # ------------------------------------------------------------------
    # block-level nodes
    # ------------------------------------------------------------------
    def _transform_block(self, node, out):
        if isinstance(node, NavigableString):
            text = str(node).strip()
            if text:
                p = out.new_tag("p")
                p.string = text
                return [p]
            return []
        if not isinstance(node, Tag):
            return []

        name = node.name
        classes = node.get("class") or []

        if name in BLOCK_PASSTHROUGH_TAGS:
            fresh = out.new_tag(name)
            self._fill_inline(node, fresh, out)
            return [fresh]

        if name == "p":
            p = out.new_tag("p")
            self._fill_inline(node, p, out)
            if not p.get_text(strip=True) and not p.find(True):
                p.clear()  # whitespace-only spacer paragraphs
            return [p]

        if name in ("ul", "ol"):
            return self._transform_list(node, out)

        if name == "pre":
            return [self._transform_code(node, out)]

        if name == "figure":
            return self._transform_figure(node, out)

        if name == "aside":
            # Notion exports callouts as <aside class="callout">
            if "callout" in classes or node.get("data-notion-callout") is not None:
                return [self._transform_callout(node, out)]
            nodes = []
            for child in list(node.children):
                nodes.extend(self._transform_block(child, out))
            return nodes

        if name == "details":
            return self._transform_toggle(node, out)

        if name == "div":
            if "column-list" in classes:
                nodes = []
                for column in node.find_all("div", class_="column", recursive=False):
                    for child in list(column.children):
                        nodes.extend(self._transform_block(child, out))
                return nodes
            if "collection-content" in classes:
                return [self._transform_database_marker(node, out)]
            if "indented" in classes or not classes:
                nodes = []
                for child in list(node.children):
                    nodes.extend(self._transform_block(child, out))
                return nodes
            # unknown wrapper — recurse into it rather than dropping content
            nodes = []
            for child in list(node.children):
                nodes.extend(self._transform_block(child, out))
            return nodes

        if name == "table":
            return [self._transform_table(node, out)]

        if name == "img":
            image = self._transform_image(node, out)
            return [image] if image is not None else []

        if name in ("header", "style", "script", "nav"):
            return []

        # anything unknown: keep the text so no content is silently lost
        text = node.get_text(" ", strip=True)
        if text:
            self._warn(f"unsupported_block:{name}")
            p = out.new_tag("p")
            p.string = text
            return [p]
        return []

    def _transform_list(self, node, out):
        classes = node.get("class") or []
        if "to-do-list" in classes:
            ul = out.new_tag("ul", attrs={"data-type": "taskList"})
            for li in node.find_all("li", recursive=False):
                checkbox = li.find("div", class_="checkbox")
                checked = bool(checkbox and "checkbox-on" in (checkbox.get("class") or []))
                item = out.new_tag(
                    "li", attrs={"data-type": "taskItem", "data-checked": "true" if checked else "false"}
                )
                if checkbox:
                    checkbox.decompose()
                p = out.new_tag("p")
                self._fill_inline(li, p, out)
                item.append(p)
                ul.append(item)
            return [ul]

        fresh = out.new_tag(node.name)
        for li in node.find_all("li", recursive=False):
            item = out.new_tag("li")
            # nested lists live inside the li — split inline content from them
            paragraph = out.new_tag("p")
            for child in list(li.children):
                if isinstance(child, Tag) and child.name in ("ul", "ol"):
                    if paragraph.contents:
                        item.append(paragraph)
                        paragraph = out.new_tag("p")
                    for nested in self._transform_list(child, out):
                        item.append(nested)
                else:
                    self._append_inline(child, paragraph, out)
            if paragraph.contents:
                item.append(paragraph)
            if not item.contents:
                item.append(out.new_tag("p"))
            fresh.append(item)
        return [fresh]

    def _transform_code(self, node, out):
        code_node = node.find("code")
        language = None
        for cls in (code_node.get("class") or []) if code_node else []:
            if cls.startswith("language-"):
                language = cls[len("language-") :]
        pre = out.new_tag("pre")
        code = out.new_tag("code")
        if language:
            code["language"] = language
        code.string = (code_node or node).get_text()
        pre.append(code)
        return pre

    def _transform_figure(self, node, out):
        classes = node.get("class") or []
        if "callout" in classes:
            return [self._transform_callout(node, out)]
        if "link-to-page" in classes or "bookmark" in classes:
            link = node.find("a")
            if link is None:
                return []
            href = self._rewrite_href(link.get("href", ""))
            if not href:
                return []
            p = out.new_tag("p")
            a = out.new_tag("a", href=href)
            a.string = link.get_text(" ", strip=True) or link.get("href", "")
            p.append(a)
            return [p]
        if "image" in classes or node.find("img"):
            image = self._transform_image(node.find("img"), out)
            return [image] if image is not None else []
        if node.find("a"):
            link = node.find("a")
            p = out.new_tag("p")
            a = out.new_tag("a", href=self._rewrite_href(link.get("href", "")))
            a.string = link.get_text(" ", strip=True) or link.get("href", "")
            p.append(a)
            return [p]
        text = node.get_text(" ", strip=True)
        if text:
            p = out.new_tag("p")
            p.string = text
            return [p]
        return []

    def _transform_callout(self, node, out):
        emoji = None
        icon_span = node.find("span", class_="icon")
        if icon_span:
            emoji_text = icon_span.get_text(strip=True)
            if emoji_text:
                emoji = emoji_text
        codepoints = "-".join(f"{ord(ch):x}" for ch in emoji) if emoji else "1f4a1"
        unicode_attr = str(ord(emoji[0])) if emoji else "128161"
        attrs = {
            "data-block-type": "callout-component",
            "data-logo-in-use": "emoji",
            "data-emoji-unicode": unicode_attr,
            "data-emoji-url": f"https://cdn.jsdelivr.net/npm/emoji-datasource-apple/img/apple/64/{codepoints}.png",
        }
        notion_background = node.get("data-notion-callout-background", "")
        background_key = NOTION_COLOR_MAP.get(notion_background.replace("_background", ""))
        if background_key:
            attrs["data-background"] = background_key
        callout = out.new_tag("div", attrs=attrs)
        content_holder = node.find("div", style=re.compile("width:100%")) or node
        appended = False
        for child in list(content_holder.children):
            if isinstance(child, Tag) and (child.find("span", class_="icon") or child.find("img", class_="icon")):
                continue
            for block in self._transform_block(child, out):
                callout.append(block)
                appended = True
        if not appended:
            p = out.new_tag("p")
            p.string = node.get_text(" ", strip=True)
            callout.append(p)
        return callout

    def _transform_toggle(self, node, out):
        nodes = []
        summary = node.find("summary")
        if summary:
            p = out.new_tag("p")
            strong = out.new_tag("strong")
            self._fill_inline(summary, strong, out)
            p.append(strong)
            nodes.append(p)
        for child in list(node.children):
            if isinstance(child, Tag) and child.name == "summary":
                continue
            nodes.extend(self._transform_block(child, out))
        return nodes

    def _transform_database_marker(self, node, out):
        database_uuid = (node.get("id") or "").replace("-", "")
        marker = out.new_tag("div", attrs={"data-notion-database": database_uuid})
        if database_uuid:
            self._result.database_refs.append(database_uuid)
        return marker

    def _transform_table(self, node, out):
        table = out.new_tag("table")
        for tr in node.find_all("tr"):
            row = out.new_tag("tr")
            for cell in tr.find_all(["th", "td"], recursive=False):
                fresh = out.new_tag(cell.name)
                p = out.new_tag("p")
                self._fill_inline(cell, p, out)
                fresh.append(p)
                row.append(fresh)
            table.append(row)
        return table

    def _transform_image(self, node, out):
        if node is None:
            return None
        src = node.get("src", "")
        if not src:
            return None
        if src.startswith("data:"):
            self._warn("data_uri_image_dropped")
            return None
        parsed = urlparse(src)
        if parsed.scheme in ("http", "https"):
            # bare Notion app links exported as images carry no content
            if parsed.netloc in ("app.notion.com", "www.notion.so", "notion.so") and not parsed.path.strip("/"):
                return None
            # remote image (e.g. Notion static icons): keep as plain img
            img = out.new_tag("img", src=src)
            if node.get("alt"):
                img["alt"] = node["alt"]
            return img
        asset_path = self._resolve_relative(src)
        if self._known_assets is not None and asset_path not in self._known_assets:
            self._warn(f"missing_asset:{asset_path}")
            return None
        self._result.asset_paths.append(asset_path)
        return out.new_tag(
            "image-component",
            attrs={"src": f"{ASSET_SCHEME}{asset_path}", "width": "100%", "height": "auto", "status": "uploaded"},
        )

    # ------------------------------------------------------------------
    # inline nodes
    # ------------------------------------------------------------------
    def _fill_inline(self, source, target, out):
        for child in list(source.children):
            self._append_inline(child, target, out)

    def _append_inline(self, node, target, out):
        if isinstance(node, NavigableString):
            target.append(str(node))
            return
        if not isinstance(node, Tag):
            return

        name = node.name
        if name in INLINE_KEEP_TAGS:
            fresh = out.new_tag("del" if name == "s" else name)
            if name == "br":
                target.append(fresh)
                return
            self._fill_inline(node, fresh, out)
            target.append(fresh)
            return

        if name == "mark":
            span = out.new_tag("span")
            for cls in node.get("class") or []:
                if not cls.startswith("highlight-"):
                    continue
                color = cls[len("highlight-") :]
                if color.endswith("_background"):
                    key = NOTION_COLOR_MAP.get(color[: -len("_background")])
                    if key:
                        span["data-background-color"] = key
                else:
                    key = NOTION_COLOR_MAP.get(color)
                    if key:
                        span["data-text-color"] = key
            if span.attrs:
                self._fill_inline(node, span, out)
                target.append(span)
            else:
                self._fill_inline(node, target, out)
            return

        if name == "a":
            href = self._rewrite_href(node.get("href", ""))
            if not href:
                self._fill_inline(node, target, out)
                return
            a = out.new_tag("a", href=href)
            self._fill_inline(node, a, out)
            if not a.get_text(strip=True) and not a.find("img"):
                return  # empty exported anchors (e.g. bare app.notion.com refs)
            target.append(a)
            return

        if name == "img":
            image = self._transform_image(node, out)
            if image is not None:
                target.append(image)
            return

        if name in ("span", "time", "label", "p", "div"):
            # block tags in inline context (e.g. <p> inside a table cell):
            # merge their content, separating from previous text with a break
            if name in ("p", "div") and target.contents:
                target.append(out.new_tag("br"))
            self._fill_inline(node, target, out)
            return

        if name in ("style", "script"):
            return

        # inline unknowns: keep the text
        text = node.get_text(" ", strip=True)
        if text:
            self._warn(f"unsupported_inline:{name}")
            target.append(text)

    # ------------------------------------------------------------------
    # comments
    # ------------------------------------------------------------------
    def _extract_comments(self, soup):
        """Pull Notion comment blocks out of the document before transforming.

        Notion's HTML export renders comments (page- and block-level) in
        dedicated containers. The exact markup is not officially documented,
        so this matches defensively on class names and data attributes and
        reports via warnings when a container could not be fully parsed.
        Extracted containers are removed so page content stays clean either
        way.
        """
        containers = []
        for element in soup.find_all(True):
            classes = " ".join(element.get("class") or []).lower()
            has_comment_class = "comment" in classes or "discussion" in classes
            has_comment_attr = any(attr.startswith("data-notion-comment") for attr in element.attrs)
            if has_comment_class or has_comment_attr:
                # keep only top-level containers, not their descendants
                if not any(element in c.descendants for c in containers):
                    containers.append(element)

        for container in containers:
            for item in self._split_comment_items(container):
                self._result.comments.append(item)
            container.decompose()

    def _split_comment_items(self, container):
        """Yield {"id", "author", "html"} for each comment inside a container."""
        # individual comments are usually repeated direct children; if none
        # look like separate items, treat the whole container as one comment
        children = [c for c in container.find_all(recursive=False) if isinstance(c, Tag)]
        items = children if len(children) > 1 else [container]
        for index, item in enumerate(items):
            author = None
            author_node = item.find(class_=re.compile("author|user", re.I))
            if author_node is None:
                author_node = item.find(["b", "strong"])
            if author_node is not None:
                author = author_node.get_text(" ", strip=True) or None
                author_node.extract()
            text = item.get_text(" ", strip=True)
            if not text:
                continue
            comment_id = item.get("id") or container.get("id") or ""
            if not comment_id:
                self._warn("comment_without_id")
            yield {
                "id": comment_id or f"{index}",
                "author": author,
                "html": f"<p>{text}</p>",
            }

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _rewrite_href(self, href):
        if not href:
            return ""
        parsed = urlparse(href)
        if parsed.scheme in ("http", "https", "mailto", "tel"):
            if parsed.netloc == "app.notion.com" and not parsed.path.strip("/"):
                return ""
            return href
        decoded = unquote(href)
        uuid_match = FILENAME_UUID_RE.search(decoded)
        if uuid_match:
            self._result.page_refs.append(uuid_match.group(1))
            return f"{PAGE_SCHEME}{uuid_match.group(1)}"
        if decoded.endswith(".csv"):
            return ""  # database links are handled by the collection marker
        # link to an exported asset file (e.g. a PDF)
        asset_path = self._resolve_relative(href)
        if self._known_assets is None or asset_path in self._known_assets:
            self._result.asset_paths.append(asset_path)
            return f"{ASSET_SCHEME}{asset_path}"
        return ""

    def _resolve_relative(self, src):
        return posixpath.normpath(posixpath.join(self._base_dir, unquote(src)))

    def _warn(self, message):
        if message not in self._result.warnings:
            self._result.warnings.append(message)

    @staticmethod
    def _merge_adjacent_lists(out):
        """Notion emits one <ul>/<ol> per item — merge consecutive siblings."""
        current = out.contents[0] if out.contents else None
        while current is not None:
            nxt = current.next_sibling
            if (
                isinstance(current, Tag)
                and isinstance(nxt, Tag)
                and current.name == nxt.name
                and current.name in ("ul", "ol")
                and current.get("data-type") == nxt.get("data-type")
            ):
                for item in list(nxt.children):
                    current.append(item.extract())
                nxt.decompose()
                continue  # re-check the same node against its new sibling
            current = nxt
