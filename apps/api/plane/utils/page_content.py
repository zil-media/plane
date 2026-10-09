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


def apply_page_content(page, description_html=None, name=None):
    """Apply a new body and/or title to `page`'s document.

    Returns {"description_binary": <base64>, "description_html", "description_json",
    "applied_to_live_document"}. Raises LiveServerUnavailable when the live server can't be reached.
    """
    if not settings.LIVE_URL or not settings.LIVE_SERVER_SECRET_KEY:
        raise LiveServerUnavailable("LIVE_BASE_URL / LIVE_SERVER_SECRET_KEY are not configured")

    payload = {
        "current_description_binary": (
            base64.b64encode(bytes(page.description_binary)).decode() if page.description_binary else ""
        ),
        "current_description_html": page.description_html or "<p></p>",
        "current_name": page.name or "",
    }
    if description_html is not None:
        payload["description_html"] = description_html
    if name is not None:
        payload["name"] = name

    url = normalize_url_path(f"{settings.LIVE_URL}/page-content/{page.id}/apply/")
    try:
        response = requests.post(
            url,
            json=payload,
            headers={"live-server-secret-key": settings.LIVE_SERVER_SECRET_KEY},
            timeout=20,
        )
    except requests.RequestException as e:
        log_exception(e)
        raise LiveServerUnavailable(str(e)) from e

    if response.status_code != 200:
        raise LiveServerUnavailable(f"live server answered {response.status_code}")
    return response.json()
