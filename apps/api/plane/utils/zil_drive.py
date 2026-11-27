# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Google Drive videos in the client portal.

The team pastes a Drive link on a work item; the portal plays the file in its own player (so a
comment can point at a second of it) straight from Google's Drive API with Ops' API key
(GOOGLE_DRIVE_API_KEY, restricted to the Drive API and Ops' domain). That needs the file shared as
"anyone with the link". When it can't (no key, a private file, Google down), the portal shows Drive's
own preview instead, which Drive itself asks access for.
"""

import logging
import re
from urllib.parse import parse_qs, quote, urlparse

import requests
from django.conf import settings
from django.core.cache import cache

log = logging.getLogger("plane.api")

API = "https://www.googleapis.com/drive/v3/files/"
FILE_ID = re.compile(r"^[A-Za-z0-9_-]{10,200}$")
FILE_PATH = re.compile(r"^/file/d/([A-Za-z0-9_-]{10,200})(?:/|$)")
OK_SECONDS = 60 * 60
FAILED_SECONDS = 5 * 60


def drive_file_id(url):
    """The file id of a Drive file link (…/file/d/<id>/view, …/open?id=<id>, …/uc?id=<id>), or None."""
    try:
        parsed = urlparse(str(url or ""))
    except ValueError:
        return None
    if parsed.scheme != "https" or parsed.hostname != "drive.google.com":
        return None
    match = FILE_PATH.match(parsed.path)
    if match:
        return match.group(1)
    if parsed.path in ("/open", "/uc"):
        file_id = (parse_qs(parsed.query).get("id") or [""])[0]
        return file_id if FILE_ID.match(file_id) else None
    return None


def _api_key():
    return str(getattr(settings, "GOOGLE_DRIVE_API_KEY", "") or "")


def _metadata(file_id):
    """{name, mimeType} of a file shared with anyone with the link, or None. Cached by file."""
    key = _api_key()
    if not key:
        return None
    cache_key = f"zil_drive_meta:{file_id}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached or None
    meta = {}
    try:
        response = requests.get(
            f"{API}{file_id}",
            params={"fields": "name,mimeType", "supportsAllDrives": "true", "key": key},
            timeout=4,
        )
        if response.status_code == 200:
            body = response.json()
            meta = {"name": str(body.get("name") or ""), "mimeType": str(body.get("mimeType") or "")}
        else:
            log.info("Drive file %s not readable for the portal: %s", file_id, response.status_code)
    except (requests.RequestException, ValueError):
        log.warning("Drive lookup failed for %s", file_id, exc_info=True)
    cache.set(cache_key, meta, OK_SECONDS if meta else FAILED_SECONDS)
    return meta or None


def drive_media(file_id, title):
    """The portal's media entry for a Drive file: played by the portal (`drive`) when it is a video
    or an image anyone with the link can see, else Drive's own preview (`drive_preview`)."""
    meta = _metadata(file_id)
    media_id = f"drive:{file_id}"
    kind = (meta or {}).get("mimeType", "").lower()
    if meta and kind.startswith(("video/", "image/")):
        stream = f"{API}{quote(file_id)}?alt=media&supportsAllDrives=true&key={quote(_api_key())}"
        return {"id": media_id, "kind": "drive", "name": meta["name"] or title, "type": kind, "url": stream}
    return {
        "id": media_id,
        "kind": "drive_preview",
        "name": (meta or {}).get("name") or title,
        "type": kind,
        "url": f"https://drive.google.com/file/d/{quote(file_id)}/preview",
    }
