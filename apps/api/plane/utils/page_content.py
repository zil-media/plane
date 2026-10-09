# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Edit a page's collaborative document from outside the editor.

A page's source of truth is its Yjs document (`description_binary`); `description_html` and
`description_json` are derived from it. Writing only `description_html` would be overwritten by the
next save of anyone who has the page open, and regenerating the binary from scratch would duplicate
content for browsers that cached the old document. So the change goes through the live server, which
applies it as a Yjs diff — on the open document when there is one — and returns every format.
"""

# Python imports
import base64

# Third party imports
import requests

# Django imports
from django.conf import settings

# Module imports
from plane.utils.exception_logger import log_exception
from plane.utils.url import normalize_url_path


class LiveServerUnavailable(Exception):
    pass


class PageEditRejected(Exception):
    """The live server refused a block edit (unknown block, ambiguous text, …); nothing changed."""


def _stored_document(page):
    return {
        "current_description_binary": (
            base64.b64encode(bytes(page.description_binary)).decode() if page.description_binary else ""
        ),
        "current_description_html": page.description_html or "<p></p>",
        "current_name": page.name or "",
    }


def _post_to_live(page, action, payload):
    if not settings.LIVE_URL or not settings.LIVE_SERVER_SECRET_KEY:
        raise LiveServerUnavailable("LIVE_BASE_URL / LIVE_SERVER_SECRET_KEY are not configured")

    url = normalize_url_path(f"{settings.LIVE_URL}/page-content/{page.id}/{action}/")
    try:
        response = requests.post(
            url,
            json={**_stored_document(page), **payload},
            headers={"live-server-secret-key": settings.LIVE_SERVER_SECRET_KEY},
            timeout=20,
        )
    except requests.RequestException as e:
        log_exception(e)
        raise LiveServerUnavailable(str(e)) from e

    if response.status_code == 422:
        raise PageEditRejected(response.json().get("message") or "The edit was rejected")
    if response.status_code != 200:
        raise LiveServerUnavailable(f"live server answered {response.status_code}")
    return response.json()


def apply_page_content(page, description_html=None, name=None):
    """Apply a new body and/or title to `page`'s document.

    Returns {"description_binary": <base64>, "description_html", "description_json",
    "applied_to_live_document"}. Raises LiveServerUnavailable when the live server can't be reached.
    """
    payload = {}
    if description_html is not None:
        payload["description_html"] = description_html
    if name is not None:
        payload["name"] = name
    return _post_to_live(page, "apply", payload)


def edit_page_blocks(page, ops):
    """Apply block-level edits (see apps/live/src/lib/page-edit/ops.ts) to `page`'s document.

    Returns the stored formats like apply_page_content, plus "changed", "summary" (one line per op),
    "blocks" (the touched blocks as markdown) and "total_blocks". Raises PageEditRejected when an op
    can't be applied (nothing changes then) and LiveServerUnavailable.
    """
    return _post_to_live(page, "edit", {"ops": ops})


def read_page_blocks(page, offset=0, limit=0, blocks=None):
    """`page` as block-annotated markdown: {"content", "total_blocks", "shown_blocks", "offset"}."""
    payload = {"offset": offset, "limit": limit}
    if blocks:
        payload["blocks"] = blocks
    return _post_to_live(page, "read", payload)
