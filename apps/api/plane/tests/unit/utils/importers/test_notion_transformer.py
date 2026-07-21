# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Unit tests for the Notion HTML -> Plane editor HTML transformer.

Loaded from file (not through the ``plane`` package) so the tests run
without Django/Celery installed — the transformer only needs bs4.
"""

import importlib.util
import pathlib

import pytest

_TRANSFORMER_PATH = (
    pathlib.Path(__file__).resolve().parents[4] / "utils" / "importers" / "notion" / "transformer.py"
)
_spec = importlib.util.spec_from_file_location("notion_transformer_under_test", _TRANSFORMER_PATH)
transformer_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(transformer_module)

NotionHTMLTransformer = transformer_module.NotionHTMLTransformer
extract_comment_authors = transformer_module.extract_comment_authors
extract_person_names = transformer_module.extract_person_names

PAGE_PATH = "Private & Shared/Root/Page abcdefabcdefabcdefabcdefabcdefab.html"
TARGET_UUID = "1234567890abcdef1234567890abcdef"


def wrap(body):
    return f'<html><head><title>T</title></head><body><article><div class="page-body">{body}</div></article></body></html>'


def transform(body, known_assets=None):
    transformer = NotionHTMLTransformer(PAGE_PATH, known_assets=known_assets)
    return transformer.transform(wrap(body))


class TestBlocks:
    def test_headings_paragraphs_hr(self):
        result = transform("<h2>Title</h2><p>Text</p><hr/>")
        assert "<h2>Title</h2>" in result.html
        assert "<p>Text</p>" in result.html
        assert "<hr/>" in result.html

    def test_consecutive_lists_are_merged(self):
        body = (
            '<ul class="bulleted-list"><li>one</li></ul>'
            '<ul class="bulleted-list"><li>two</li></ul>'
        )
        result = transform(body)
        assert result.html.count("<ul>") == 1
        assert result.html.count("<li>") == 2

    def test_todo_list_becomes_task_list(self):
        # real export markup: <input class="checkbox checkbox-on" checked>
        # plus the to-do-children span and an empty indented div
        body = (
            '<ul class="to-do-list">'
            '<li><input type="checkbox" class="checkbox checkbox-on" disabled="" checked=""/>'
            '<span class="to-do-children-checked">done item</span><div class="indented"></div></li>'
            "</ul>"
            '<ul class="to-do-list">'
            '<li><input type="checkbox" class="checkbox checkbox-off" disabled=""/>'
            '<span class="to-do-children-unchecked">pending item</span><div class="indented"></div></li>'
            "</ul>"
        )
        result = transform(body)
        assert 'data-type="taskList"' in result.html
        # correlation matters: the checked item must be the one that was checked
        import re as _re
        items = _re.findall(r'data-checked="(true|false)"[^>]*>\s*<p>([^<]*)', result.html)
        assert ("true", "done item") in items
        assert ("false", "pending item") in items
        # the empty indented spacer must not leave a stray <br/>
        assert "<br/>" not in result.html

    def test_todo_list_legacy_div_checkbox(self):
        body = '<ul class="to-do-list"><li><div class="checkbox checkbox-on"></div>done</li></ul>'
        result = transform(body)
        assert 'data-checked="true"' in result.html

    def test_columns_are_flattened_in_order(self):
        body = (
            '<div class="column-list">'
            '<div class="column"><p>first</p></div>'
            '<div class="column"><p>second</p></div>'
            "</div>"
        )
        result = transform(body)
        assert result.html.index("first") < result.html.index("second")
        assert "column" not in result.html

    def test_toggle_becomes_bold_paragraph_plus_content(self):
        body = "<details><summary>Reveal</summary><p>hidden</p></details>"
        result = transform(body)
        assert "<strong>Reveal</strong>" in result.html
        assert "<p>hidden</p>" in result.html
        assert "<details>" not in result.html

    def test_code_block_language(self):
        body = '<pre class="code"><code class="language-python">print(1)</code></pre>'
        result = transform(body)
        assert '<code language="python">' in result.html

    def test_simple_table(self):
        body = "<table><tr><td>cell</td></tr></table>"
        result = transform(body)
        assert "<table><tr><td><p>cell</p></td></tr></table>" in result.html


class TestMarksAndLinks:
    def test_highlight_text_color_mapped(self):
        result = transform('<p><mark class="highlight-blue">colored</mark></p>')
        assert '<span data-text-color="light-blue">colored</span>' in result.html

    def test_highlight_background_mapped(self):
        result = transform('<p><mark class="highlight-yellow_background">hl</mark></p>')
        assert '<span data-background-color="peach">hl</span>' in result.html

    def test_default_highlight_unwrapped(self):
        result = transform('<p><mark class="highlight-default">plain</mark></p>')
        assert "<span" not in result.html
        assert "plain" in result.html

    def test_internal_link_rewritten_and_tracked(self):
        body = f'<p><a href="Page/Target%20{TARGET_UUID}.html">Target</a></p>'
        result = transform(body)
        assert f'href="notion-page://{TARGET_UUID}"' in result.html
        assert TARGET_UUID in result.page_refs

    def test_link_to_page_figure(self):
        body = (
            f'<figure class="link-to-page"><a href="Page/Target%20{TARGET_UUID}.html">'
            f'<img class="icon" src="https://app.notion.com/icons/x.svg"/>Target</a></figure>'
        )
        result = transform(body)
        assert ">Target</a>" in result.html
        assert TARGET_UUID in result.page_refs
        assert "icons/x.svg" not in result.html  # icon img dropped from the link

    def test_external_link_kept(self):
        result = transform('<p><a href="https://example.com/x">ext</a></p>')
        assert 'href="https://example.com/x"' in result.html

    def test_asset_link_rewritten(self):
        asset = "Private & Shared/Root/Page/file.pdf"
        result = transform('<p><a href="Page/file.pdf">PDF</a></p>', known_assets={asset})
        # & is entity-escaped in the serialized html
        assert f'href="notion-asset://{asset.replace("&", "&amp;")}"' in result.html
        assert asset in result.asset_paths


class TestImages:
    def test_local_image_becomes_image_component(self):
        asset = "Private & Shared/Root/Page/pic.png"
        result = transform('<figure class="image"><img src="Page/pic.png"/></figure>', known_assets={asset})
        # & is entity-escaped in the serialized html
        assert f'src="notion-asset://{asset.replace("&", "&amp;")}"' in result.html
        assert "<image-component" in result.html
        assert asset in result.asset_paths

    def test_data_uri_dropped_with_warning(self):
        result = transform('<p><img src="data:image/png;base64,AAAA"/></p>')
        assert "data:" not in result.html
        assert "data_uri_image_dropped" in result.warnings

    def test_bare_notion_link_image_dropped(self):
        result = transform('<p><img src="https://app.notion.com"/></p>')
        assert "<img" not in result.html

    def test_remote_image_kept_as_plain_img(self):
        result = transform('<p><img src="https://cdn.example.com/a.png"/></p>')
        assert '<img src="https://cdn.example.com/a.png"/>' in result.html


class TestDatabasesAndCallouts:
    def test_collection_marker(self):
        db_uuid = "9" * 32
        dashed = f"{db_uuid[:8]}-{db_uuid[8:12]}-{db_uuid[12:16]}-{db_uuid[16:20]}-{db_uuid[20:]}"
        body = f'<div id="{dashed}" class="collection-content"><h4>DB</h4><table></table></div>'
        result = transform(body)
        assert f'data-notion-database="{db_uuid}"' in result.html
        assert db_uuid in result.database_refs

    def test_collection_wrapper_marker_falls_back_to_page_uuid(self):
        # new-format (2025 "data sources") export: the collection node has no
        # database id — the marker carries the page uuid plus the row uuids
        row_uuid = "5" * 32
        dashed = f"{row_uuid[:8]}-{row_uuid[8:12]}-{row_uuid[12:16]}-{row_uuid[16:20]}-{row_uuid[20:]}"
        body = (
            '<div class="collection-content-wrapper"><table class="collection-content">'
            f'<tbody><tr id="{dashed}"><td>Alpha</td></tr></tbody></table></div>'
        )
        result = transform(body)
        assert 'data-notion-database="abcdefabcdefabcdefabcdefabcdefab"' in result.html
        assert f'data-notion-rows="{row_uuid}"' in result.html

    def test_bare_collection_table_becomes_marker(self):
        body = '<table class="collection-content"><tbody><tr><td>x</td></tr></tbody></table>'
        result = transform(body)
        assert "data-notion-database" in result.html
        assert "<td>" not in result.html

    def test_aside_callout_with_background(self):
        body = (
            '<aside class="block-color-gray_background callout" data-notion-callout=""'
            ' data-notion-callout-background="gray_background">'
            '<div style="font-size:1.5em"><img class="icon" src="https://app.notion.com/icons/i.svg"/></div>'
            '<div style="width:100%"><p>callout text</p></div>'
            "</aside>"
        )
        result = transform(body)
        assert 'data-block-type="callout-component"' in result.html
        assert 'data-background="gray"' in result.html
        assert "callout text" in result.html

    def test_figure_callout_with_emoji(self):
        body = (
            '<figure class="callout"><div style="font-size:1.5em"><span class="icon">💡</span></div>'
            '<div style="width:100%"><p>tip</p></div></figure>'
        )
        result = transform(body)
        assert 'data-block-type="callout-component"' in result.html
        assert "tip" in result.html

    def test_callout_emoji_from_data_attribute(self):
        # real exports leave the icon span empty and carry the glyph in data-emoji
        body = (
            '<aside class="callout" data-notion-callout="">'
            '<div style="font-size:1.5em"><span class="icon" data-emoji="🚀"></span></div>'
            '<div style="width:100%"><p>launch</p></div></aside>'
        )
        result = transform(body)
        assert f'data-emoji-unicode="{ord("🚀")}"' in result.html

    def test_unclassed_attachment_figure_keeps_link_and_strips_prefix(self):
        # real export shape: classless <figure> with the url in <div class="source">
        # and an attachment:<uuid>: prefix in the link text
        body = (
            '<figure id="391dd4d7" dir="ltr"><div class="source">'
            '<a href="Doc/Propuesta.pdf">attachment:228e782a-c4d9-4f4b-a3af-2fe516a9af0f:Propuesta.pdf</a>'
            "</div></figure>"
        )
        result = transform(body, known_assets={"Private & Shared/Root/Doc/Propuesta.pdf"})
        assert "attachment:" not in result.html
        assert "Propuesta.pdf" in result.html
        assert "notion-asset://" in result.html  # link preserved, not plain text

    def test_broken_notion_embed_artifact_dropped(self):
        # real export shape: the artifact appears both as a link-to-page figure
        # (link-only, dropped whole) and inline inside surrounding prose
        body = (
            '<figure class="link-to-page"><a href="https://app.notion.comundefined">Página</a></figure>'
            '<p>before <a href="https://app.notion.comundefined">inline</a> after</p>'
        )
        result = transform(body)
        assert "app.notion.comundefined" not in result.html
        # inline text survives with the dead link stripped
        assert "before" in result.html and "inline" in result.html and "after" in result.html
        assert "<a " not in result.html  # no dead anchors left


class TestProperties:
    HEADER = (
        '<table class="properties"><tbody>'
        '<tr class="property-row property-row-multi_select"><th><span class="icon">i</span>Diseños</th>'
        '<td><span class="selected-value">Web</span><span class="selected-value">Branding</span></td></tr>'
        '<tr class="property-row property-row-person"><th>Lead</th>'
        '<td><span class="user"><span class="icon"><span>J</span></span>Joaquin Mesa</span></td></tr>'
        '<tr class="property-row property-row-status"><th>Estado</th>'
        '<td><span class="status-value"><div class="status-dot"></div>Correcciones</span></td></tr>'
        '<tr class="property-row property-row-date"><th>Timeline</th>'
        '<td><time datetime="2026-10-01">October 1, 2026 → December 15, 2026</time></td></tr>'
        "</tbody></table>"
    )

    def transform_with_header(self):
        transformer = NotionHTMLTransformer(PAGE_PATH)
        html = (
            f"<html><body><article><header>{self.HEADER}</header>"
            '<div class="page-body"><p>body</p></div></article></body></html>'
        )
        return transformer.transform(html)

    def test_typed_properties_extracted(self):
        props = {p["name"]: p for p in self.transform_with_header().properties}
        assert props["Diseños"]["values"] == ["Web", "Branding"]
        # the letter avatar must not pollute the person name
        assert props["Lead"]["values"] == ["Joaquin Mesa"]
        assert props["Estado"]["type"] == "status"
        assert props["Estado"]["values"] == ["Correcciones"]

    def test_date_range_parsed(self):
        props = {p["name"]: p for p in self.transform_with_header().properties}
        assert props["Timeline"]["start"] == "2026-10-01"
        assert props["Timeline"]["end"] == "2026-12-15"

    def test_spanish_date_text_parsed(self):
        assert transformer_module._parse_date_text("15 de diciembre de 2026") == "2026-12-15"

    def test_multi_select_colors_extracted(self):
        header = (
            '<table class="properties"><tbody>'
            '<tr class="property-row property-row-multi_select"><th>Diseños</th>'
            '<td><span class="selected-value select-value-color-blue">Web</span>'
            '<span class="selected-value select-value-color-green">Branding</span></td></tr>'
            "</tbody></table>"
        )
        transformer = NotionHTMLTransformer(PAGE_PATH)
        result = transformer.transform(
            f"<html><body><article><header>{header}</header>"
            '<div class="page-body"><p>x</p></div></article></body></html>'
        )
        prop = result.properties[0]
        assert prop["colors"]["Web"] == "#3b82f6"
        assert prop["colors"]["Branding"] == "#22c55e"

    def test_attachment_prefix_stripped_from_link_text(self):
        assert transformer_module._clean_link_text("attachment:abc-123:Report.pdf") == "Report.pdf"
        assert transformer_module._clean_link_text("Plain label") == "Plain label"

    def test_checkbox_property_extracted(self):
        header = (
            '<table class="properties"><tbody>'
            '<tr class="property-row property-row-checkbox"><th>Activo</th>'
            '<td><div class="checkbox checkbox-on"></div></td></tr>'
            '<tr class="property-row property-row-checkbox"><th>Archivado</th>'
            '<td><input type="checkbox" class="checkbox checkbox-off" disabled=""/></td></tr>'
            "</tbody></table>"
        )
        transformer = NotionHTMLTransformer(PAGE_PATH)
        result = transformer.transform(
            f"<html><body><article><header>{header}</header>"
            '<div class="page-body"><p>x</p></div></article></body></html>'
        )
        props = {p["name"]: p for p in result.properties}
        assert props["Activo"]["values"] == ["Yes"]
        assert props["Archivado"]["values"] == ["No"]

    def test_properties_do_not_leak_into_html(self):
        result = self.transform_with_header()
        assert "Correcciones" not in result.html
        assert result.html == "<p>body</p>"

    def test_extract_person_names(self):
        html = f"<html><body><article><header>{self.HEADER}</header></article></body></html>"
        assert extract_person_names(html) == {"Joaquin Mesa"}


class TestComments:
    COMMENTED = (
        "<p>content</p>"
        '<div class="comments" id="block-1">'
        '<div class="comment"><span class="comment-author">Ana García</span><p>first comment</p></div>'
        '<div class="comment"><b>Luis Pérez</b><p>second comment</p></div>'
        "</div>"
    )

    def test_comments_extracted_and_removed_from_body(self):
        result = transform(self.COMMENTED)
        assert "first comment" not in result.html
        assert len(result.comments) == 2
        authors = {comment["author"] for comment in result.comments}
        assert authors == {"Ana García", "Luis Pérez"}

    def test_extract_comment_authors_helper(self):
        authors = extract_comment_authors(wrap(self.COMMENTED))
        assert authors == {"Ana García", "Luis Pérez"}

    def test_page_without_comments(self):
        result = transform("<p>solo</p>")
        assert result.comments == []

    def test_replies_without_own_id_get_distinct_ids(self):
        # two same-text replies in one thread must not share a comment id, or
        # the import task's (uuid, id, html) dedup would drop the duplicate
        body = (
            '<div class="discussion" id="thread-1">'
            '<div class="comment"><b>Ana</b><p>ok</p></div>'
            '<div class="comment"><b>Ana</b><p>ok</p></div>'
            "</div>"
        )
        result = transform(body)
        assert len(result.comments) == 2
        ids = [c["id"] for c in result.comments]
        assert ids[0] != ids[1]

    def test_idless_comments_across_containers_are_distinct(self):
        # two separate id-less single-comment blocks on one page each restart
        # local enumeration at 0 — the page-global counter must keep them apart
        body = (
            '<div class="comment"><p>first thread</p></div>'
            '<div class="comment"><p>second thread</p></div>'
        )
        result = transform(body)
        assert len(result.comments) == 2
        assert result.comments[0]["id"] != result.comments[1]["id"]
        assert result.comments[0]["stable_id"] is False

    def test_comment_with_own_id_is_stable(self):
        body = '<div class="comment" id="c-real"><b>Ana</b><p>hi</p></div>'
        result = transform(body)
        assert result.comments[0]["stable_id"] is True

    def test_comment_html_escapes_markup(self):
        # entity-encoded markup in an export comment must not become live HTML
        malicious = (
            '<div class="comments" id="b1">'
            '<div class="comment"><span class="comment-author">X</span>'
            "<p>&lt;img src=x onerror=alert(1)&gt;</p></div>"
            "</div>"
        )
        result = transform(malicious)
        assert len(result.comments) == 1
        html = result.comments[0]["html"]
        assert "<img" not in html
        assert "&lt;img src=x onerror=alert(1)&gt;" in html


class TestOutputHygiene:
    def test_whitespace_paragraphs_emptied(self):
        result = transform("<p>\n</p>")
        assert "<p></p>" in result.html

    def test_empty_body_falls_back_to_paragraph(self):
        result = transform("")
        assert result.html == "<p></p>"

    def test_unknown_block_keeps_text_with_warning(self):
        result = transform("<blink>legacy text</blink>")
        assert "legacy text" in result.html
        assert any(w.startswith("unsupported_block") for w in result.warnings)
