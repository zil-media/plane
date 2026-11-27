# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Google Drive videos in the client portal.

The team pastes a Drive link on a work item; the portal plays the file in its own player (so a
comment can point at a second of it). Ops reads the file as the team member who pasted the link,
with a short-lived read-only Drive token Zil Workspace mints from its service account
(POST /api/zil/drive-token): the client sees exactly what that person could open, nothing else,
and the token never leaves Ops (the video goes through Ops' own streaming endpoint).

When it can't (Workspace or Google down, a person without a Zil Workspace account, a file they
can't open), the client reads that the video is being processed, and the team sees the warning on
the work item in Ops (`check_drive_link`).
"""

import logging
import re
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

import requests
from django.core.cache import cache

from plane.utils.zil_client import ZilUnavailable, _post, zil_enabled

log = logging.getLogger("plane.api")

API = "https://www.googleapis.com/drive/v3/files/"
FILE_ID = re.compile(r"^[A-Za-z0-9_-]{10,200}$")
FILE_PATH = re.compile(r"^/file/d/([A-Za-z0-9_-]{10,200})(?:/|$)")
META_SECONDS = 60 * 60
FAILED_SECONDS = 2 * 60
BROKEN_SECONDS = 10 * 60
# a token is reused until a minute before it expires
TOKEN_MARGIN = 60


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


def _token_state(email):
    """("ok", token) | ("refused", None) when Workspace says no for that person | ("unknown", None)."""
    email = str(email or "").strip().lower()
    if not email:
        return "refused", None
    if not zil_enabled():
        return "unknown", None
    key = f"zil_drive_token:{email}"
    cached = cache.get(key)
    if cached is not None:
        return cached
    state, ttl = ("unknown", None), FAILED_SECONDS
    try:
        response = _post("/api/zil/drive-token", {"email": email})
        if response.status_code == 200:
            body = response.json()
            token = str(body.get("accessToken") or "")
            expires = datetime.fromisoformat(str(body.get("expiresAt")).replace("Z", "+00:00"))
            ttl = int((expires - datetime.now(timezone.utc)).total_seconds()) - TOKEN_MARGIN
            if token and ttl > 0:
                state = ("ok", token)
            else:
                ttl = FAILED_SECONDS
        elif response.status_code == 404:
            # not an active person of the team: nobody can read the file as them
            state = ("refused", None)
        else:
            log.info("Workspace gave no Drive token for the portal: %s", response.status_code)
    except (ZilUnavailable, ValueError, TypeError):
        log.warning("Drive token from Workspace failed", exc_info=True)
    cache.set(key, state, ttl)
    return state


def drive_token(email):
    """A read-only Drive token acting as `email` (a Zil Workspace account), or None. Cached."""
    return _token_state(email)[1]


def _lookup(file_id, email, fresh=False):
    """{"status": "ok" | "broken" | "unknown", "meta": {name, mimeType} | None} of the file as `email`
    sees it. "broken" only when it is certain (no such person, Google says not found or no access);
    a timeout or an outage is "unknown". Cached by file and person."""
    email = str(email or "").strip().lower()
    cache_key = f"zil_drive_meta:{email}:{file_id}"
    if fresh:
        cache.delete(cache_key)
    else:
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
    state, token = _token_state(email)
    result = {"status": "broken" if state == "refused" else "unknown", "meta": None}
    if token:
        try:
            response = requests.get(
                f"{API}{file_id}",
                params={"fields": "name,mimeType", "supportsAllDrives": "true"},
                headers={"Authorization": f"Bearer {token}"},
                timeout=4,
            )
            if response.status_code == 200:
                body = response.json()
                meta = {"name": str(body.get("name") or ""), "mimeType": str(body.get("mimeType") or "").lower()}
                result = {"status": "ok", "meta": meta}
            elif response.status_code in (403, 404):
                result = {"status": "broken", "meta": None}
                log.info("Drive file %s not readable for the portal: %s", file_id, response.status_code)
            else:
                log.info("Drive lookup for %s answered %s", file_id, response.status_code)
        except (requests.RequestException, ValueError):
            log.warning("Drive lookup failed for %s", file_id, exc_info=True)
    ttl = {"ok": META_SECONDS, "broken": BROKEN_SECONDS}.get(result["status"], FAILED_SECONDS)
    cache.set(cache_key, result, ttl)
    return result


def playable(file_id, email):
    """The file's {name, mimeType} when the portal can play it (a video or an image), else None."""
    meta = _lookup(file_id, email)["meta"]
    if meta and meta["mimeType"].startswith(("video/", "image/")):
        return meta
    return None


def record_status(link, status):
    """Keep on the link whether the client can open its Drive file ("ok" / "broken"), for the
    team's warning in Ops; an "unknown" (an outage) leaves what was known."""
    if status not in ("ok", "broken"):
        return
    metadata = dict(link.metadata or {})
    if (metadata.get("zil_drive") or {}).get("status") == status:
        return
    metadata["zil_drive"] = {"status": status, "checked_at": datetime.now(timezone.utc).isoformat()}
    type(link).objects.filter(pk=link.pk).update(metadata=metadata)
    link.metadata = metadata


def check_link(link, fresh=False):
    """Check a work item link's Drive file as whoever pasted it and keep the result on the link.
    Returns the status, or None when it isn't a Drive file link."""
    file_id = drive_file_id(link.url)
    if not file_id:
        return None
    email = link.created_by.email if link.created_by_id and link.created_by else ""
    status = _lookup(file_id, email, fresh=fresh)["status"]
    record_status(link, status)
    return status


def drive_media(file_id, title, email, stream_url):
    """The portal's media entry for a Drive file linked by `email`: played by the portal through
    `stream_url` (`drive`), or `unavailable` when Ops can't read it now."""
    meta = playable(file_id, email)
    media_id = f"drive:{file_id}"
    if meta:
        return {
            "id": media_id,
            "kind": "drive",
            "name": meta["name"] or title,
            "type": meta["mimeType"],
            "url": stream_url,
        }
    # the client reads "this video is being processed"; the team sees the warning in Ops
    return {"id": media_id, "kind": "unavailable", "name": title, "type": "", "url": ""}


def open_stream(file_id, email, byte_range):
    """Google's response with the file's bytes (`byte_range` is a "bytes=…" header or None), or None."""
    token = drive_token(email)
    if not token:
        return None
    headers = {"Authorization": f"Bearer {token}"}
    if byte_range:
        headers["Range"] = byte_range
    try:
        response = requests.get(
            f"{API}{file_id}",
            params={"alt": "media", "supportsAllDrives": "true"},
            headers=headers,
            stream=True,
            timeout=(4, 30),
        )
    except requests.RequestException:
        log.warning("Drive stream failed for %s", file_id, exc_info=True)
        return None
    if response.status_code not in (200, 206):
        response.close()
        return None
    return response
