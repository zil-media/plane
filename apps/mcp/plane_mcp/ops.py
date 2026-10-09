"""Zil Ops: the Plane fork this server is vendored into (apps/mcp in the Ops monorepo).

Ops serves project pages over its API-key API (``/api/v1/.../pages/``), including block-level reads
and edits that Ops applies to the page's collaborative document. Everything Ops-specific in this
package goes through here; it is active when ``OPS_PUBLIC_URL`` is set.
"""

from __future__ import annotations

import os
from typing import Any

import requests
from plane import PlaneClient
from plane.errors.errors import HttpError

TIMEOUT_SECONDS = 30


def ops_enabled() -> bool:
    return bool(os.getenv("OPS_PUBLIC_URL", "").strip())


def api_base_url() -> str:
    return (os.getenv("PLANE_INTERNAL_BASE_URL") or os.getenv("PLANE_BASE_URL", "")).rstrip("/")


def _error(response: requests.Response) -> HttpError:
    try:
        body = response.json()
    except ValueError:
        return HttpError(response.text[:500] or response.reason, response.status_code)
    if isinstance(body, dict):
        message = body.get("error") or body.get("detail") or body.get("error_message") or body
    else:
        message = body
    # the parsed body, as the SDK's HttpError expects (it appends details not already in the message)
    return HttpError(str(message), response.status_code, body)


class OpsSession:
    """HTTP calls to the Ops API with the caller's API token."""

    def __init__(self, client: PlaneClient, workspace_slug: str):
        api_key = client.config.api_key
        if not api_key:
            raise ValueError("Zil Ops calls need an API token (OAuth connection or x-api-key).")
        if not workspace_slug:
            raise ValueError("No workspace selected for this connection.")
        self.api_key = api_key
        self.workspace_slug = workspace_slug

    def _request(self, method: str, url: str, **kwargs: Any) -> Any:
        response = requests.request(method, url, headers={"X-Api-Key": self.api_key}, timeout=TIMEOUT_SECONDS, **kwargs)
        if response.status_code >= 400:
            raise _error(response)
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    def api(self, method: str, path: str, **kwargs: Any) -> Any:
        return self._request(method, f"{api_base_url()}/api/v1/workspaces/{self.workspace_slug}/{path}", **kwargs)

    def page(self, method: str, project_id: str, page_id: str = "", action: str = "", **kwargs: Any) -> Any:
        path = f"projects/{project_id}/pages/" + (f"{page_id}/" if page_id else "") + (f"{action}/" if action else "")
        return self.api(method, path, **kwargs)
