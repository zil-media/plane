# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Read-only client for Zil Workspace clients (MgmtClient), used to link folders.

Zil is the source of truth for clients; Plane only searches them and caches
display fields on PageZilClientLink. Requires ZIL_BASE_URL + ZIL_SERVICE_SECRET.
"""

# Python imports
import os
import re

# Third party imports
import requests

# Django imports
from django.utils import timezone

# Module imports
from plane.utils.exception_logger import log_exception

OBJECT_ID_RE = re.compile(r"^[a-f0-9]{24}$")
ZIL_TIMEOUT_SECONDS = 4


class ZilUnavailable(Exception):
    pass


def apply_zil_client_fields(link, client):
    """Copy Zil's client DTO into a PageZilClientLink's cached display fields."""
    link.alias = (client.get("alias") or "")[:255]
    link.company_name = (client.get("companyName") or "")[:255]
    link.lifecycle_status = (client.get("lifecycleStatus") or "")[:32]
    link.business_unit_slug = (client.get("businessUnitSlug") or "")[:64]
    link.synced_at = timezone.now()


def zil_enabled():
    return bool(os.environ.get("ZIL_BASE_URL") and os.environ.get("ZIL_SERVICE_SECRET"))


def is_valid_client_id(client_id):
    return bool(client_id) and bool(OBJECT_ID_RE.match(str(client_id)))


def _get(path, params):
    base = os.environ.get("ZIL_BASE_URL", "").rstrip("/")
    secret = os.environ.get("ZIL_SERVICE_SECRET", "")
    try:
        return requests.get(
            f"{base}{path}",
            params=params,
            headers={"X-Zil-Service-Key": secret},
            timeout=ZIL_TIMEOUT_SECONDS,
        )
    except Exception as e:
        log_exception(e)
        raise ZilUnavailable() from e


def search_zil_clients(workspace_slug, q="", limit=20):
    """Active clients of the Business Units mapped to this workspace. Raises ZilUnavailable."""
    resp = _get("/api/sso/clients", {"workspaceSlug": workspace_slug, "q": q[:100], "limit": limit})
    if resp.status_code != 200:
        raise ZilUnavailable()
    try:
        return resp.json().get("clients") or []
    except ValueError as e:
        raise ZilUnavailable() from e


def get_zil_client(workspace_slug, client_id):
    """A single client, or None when it doesn't exist or belongs to another workspace's BUs."""
    if not is_valid_client_id(client_id):
        return None
    resp = _get(f"/api/sso/clients/{client_id}", {"workspaceSlug": workspace_slug})
    if resp.status_code == 404:
        return None
    if resp.status_code != 200:
        raise ZilUnavailable()
    try:
        return resp.json().get("client")
    except ValueError as e:
        raise ZilUnavailable() from e
