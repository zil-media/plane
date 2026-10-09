"""Zil Ops: the Plane fork this server is vendored into (apps/mcp in the Ops monorepo).

Ops serves project pages over its API-key API (``/api/v1/.../pages/``) and edits page content
through its live server, on the collaborative document, block by block. Everything Ops-specific in
this package goes through here; it is active when ``OPS_LIVE_URL`` is set.
"""

from __future__ import annotations

import os
from typing import Any

import requests
from plane import PlaneClient
from plane.errors.errors import HttpError

TIMEOUT_SECONDS = 30


def ops_enabled() -> bool:
    return bool(os.getenv("OPS_LIVE_URL", "").strip())


def api_base_url() -> str:
    return (os.getenv("PLANE_INTERNAL_BASE_URL") or os.getenv("PLANE_BASE_URL", "")).rstrip("/")


def live_base_url() -> str:
    return os.getenv("OPS_LIVE_URL", "").rstrip("/")


def _error_message(response: requests.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:500] or response.reason
    if isinstance(body, dict):
        return str(body.get("error") or body.get("detail") or body.get("error_message") or body)
    return str(body)


class OpsSession:
    """HTTP calls to the Ops API and live server with the caller's API token."""

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
            raise HttpError(_error_message(response), response.status_code, response)
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    def api(self, method: str, path: str, **kwargs: Any) -> Any:
        return self._request(method, f"{api_base_url()}/api/v1/workspaces/{self.workspace_slug}/{path}", **kwargs)

    def live(self, method: str, path: str, **kwargs: Any) -> Any:
        return self._request(method, f"{live_base_url()}/agent/pages/{path}", **kwargs)

    def scope(self, project_id: str) -> dict[str, str]:
        return {"workspace_slug": self.workspace_slug, "project_id": project_id}
