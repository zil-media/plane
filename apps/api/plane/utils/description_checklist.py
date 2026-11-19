# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Count the to-do list items of a rich-text description.

The editor stores a task list item as ``<li data-type="taskItem" data-checked="true|false">``.
Nested items count too. Anything unparseable counts as an empty checklist: this runs inside
Issue.save(), so it must never raise.
"""

from html.parser import HTMLParser

from plane.utils.exception_logger import log_exception


class _TaskItemCounter(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.total = 0
        self.completed = 0

    def handle_starttag(self, tag, attrs):
        if tag != "li":
            return
        attributes = dict(attrs)
        if (attributes.get("data-type") or "").strip() != "taskItem":
            return
        self.total += 1
        if (attributes.get("data-checked") or "").strip().lower() == "true":
            self.completed += 1

    # A self-closing <li/> is still an item.
    handle_startendtag = handle_starttag


def count_checklist(html):
    """Return ``(total, completed)`` task items in ``html``; ``(0, 0)`` when there are none."""
    if not html or not isinstance(html, str) or "taskItem" not in html:
        return 0, 0
    try:
        parser = _TaskItemCounter()
        parser.feed(html)
        parser.close()
        return parser.total, parser.completed
    except Exception as e:
        log_exception(e, warning=True)
        return 0, 0
