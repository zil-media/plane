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
        body = (
            '<ul class="to-do-list">'
            '<li><div class="checkbox checkbox-on"></div>done item</li>'
            "</ul>"
            '<ul class="to-do-list">'
            '<li><div class="checkbox checkbox-off"></div>pending item</li>'
            "</ul>"
        )
        result = transform(body)
        assert 'data-type="taskList"' in result.html
        assert 'data-checked="true"' in result.html
        assert 'data-checked="false"' in result.html

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
