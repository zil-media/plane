# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import pytest

from plane.utils.description_checklist import count_checklist


def _item(checked, text="x", inner=""):
    return (
        f'<li data-type="taskItem" data-checked="{"true" if checked else "false"}">'
        f'<label><input type="checkbox"></label><div><p>{text}</p>{inner}</div></li>'
    )


@pytest.mark.unit
class TestCountChecklist:
    @pytest.mark.parametrize("html", [None, "", "<p></p>", 123, "<p>plain text</p>"])
    def test_empty_or_no_task_list(self, html):
        assert count_checklist(html) == (0, 0)

    def test_regular_lists_do_not_count(self):
        assert count_checklist("<ul><li>a</li><li>b</li></ul><ol><li>c</li></ol>") == (0, 0)

    def test_counts_checked_and_total(self):
        html = '<ul data-type="taskList">' + _item(True) + _item(False) + _item(True) + "</ul>"
        assert count_checklist(html) == (3, 2)

    def test_nested_items_count(self):
        nested = '<ul data-type="taskList">' + _item(True) + _item(False) + "</ul>"
        html = '<ul data-type="taskList">' + _item(False, inner=nested) + "</ul>"
        assert count_checklist(html) == (3, 1)

    def test_mixed_content_and_multiple_lists(self):
        html = (
            "<h2>Videos</h2><ul><li>bullet</li></ul>"
            '<ul data-type="taskList">' + _item(True) + "</ul>"
            "<p>taskItem in text does not count</p>"
            '<ul data-type="taskList">' + _item(False) + _item(True) + "</ul>"
        )
        assert count_checklist(html) == (3, 2)

    def test_malformed_html_never_raises(self):
        html = '<ul data-type="taskList"><li data-type="taskItem" data-checked="true"><p>open <b>tags'
        assert count_checklist(html) == (1, 1)
        assert count_checklist('<li data-type="taskItem" data-checked=') == (0, 0)

    def test_missing_checked_attribute_counts_as_unchecked(self):
        assert count_checklist('<li data-type="taskItem"><p>a</p></li>') == (1, 0)
