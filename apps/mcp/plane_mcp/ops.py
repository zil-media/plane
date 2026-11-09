"""Zil Ops: the Plane fork this server is vendored into (apps/mcp in the Ops monorepo).

Ops serves project pages over its API-key API (``/api/v1/.../pages/``), including block-level reads
and edits that Ops applies to the page's collaborative document. Everything Ops-specific in this
package goes through here; it is active when ``OPS_PUBLIC_URL`` is set.
"""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse

import requests
from plane import PlaneClient
from plane.errors.errors import HttpError

TIMEOUT_SECONDS = 30


def ops_enabled() -> bool:
    return bool(os.getenv("OPS_PUBLIC_URL", "").strip())


def public_origin_headers() -> dict[str, str]:
    """Headers that make the API see the public origin instead of the internal one (api:8000).

    Self-hosted Plane builds presigned upload/download URLs from the request's host and scheme;
    called on the internal address it hands out http://api:8000/uploads/..., which only the API
    container answers (404). With the public host the URLs go through the proxy to MinIO, like the
    browser's do.
    """
    public = urlparse(os.getenv("OPS_PUBLIC_URL", "").strip())
    if not public.netloc:
        return {}
    return {"Host": public.netloc, "X-Forwarded-Proto": public.scheme or "https"}


def storage_internal_url() -> str:
    """Where this container reaches the object store directly (the proxy sends /uploads there)."""
    return os.getenv("OPS_STORAGE_INTERNAL_URL", "http://plane-minio:9000").rstrip("/")


def internal_storage_target(url: str, headers: dict[str, str] | None = None) -> tuple[str, dict[str, str]]:
    """A presigned URL on the public origin, rewritten to reach the object store from inside.

    Going out through the public URL hits the CDN, which blocks server clients (403). MinIO checks
    the signature against the Host header, so the request keeps the public host it was signed for.
    """
    headers = dict(headers or {})
    public = urlparse(os.getenv("OPS_PUBLIC_URL", "").strip())
    target = urlparse(url)
    internal = storage_internal_url()
    if not public.netloc or target.netloc != public.netloc or not internal:
        return url, headers
    inner = urlparse(internal)
    rewritten = target._replace(scheme=inner.scheme, netloc=inner.netloc).geturl()
    headers.setdefault("Host", public.netloc)
    return rewritten, headers


class _StorageRequests:
    """``requests`` as the attachment code uses it, with presigned URLs sent inside."""

    def __getattr__(self, name: str) -> Any:
        return getattr(requests, name)

    def get(self, url: str, **kwargs: Any) -> requests.Response:
        url, kwargs["headers"] = internal_storage_target(url, kwargs.get("headers"))
        return requests.get(url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> requests.Response:
        url, kwargs["headers"] = internal_storage_target(url, kwargs.get("headers"))
        return requests.post(url, **kwargs)


storage_requests = _StorageRequests()
_origin_installed = False


def install_public_origin() -> None:
    """Make presigned attachment URLs work from this container (idempotent).

    SDK calls carry the public origin, so the API signs URLs for it; the attachment upload/download
    then goes straight to the object store with that host.
    """
    global _origin_installed
    if _origin_installed or not public_origin_headers():
        return
    import plane.api.work_items.attachments as sdk_attachments
    from plane.api.base_resource import BaseResource

    import plane_mcp.tools.work_item_attachments as mcp_attachments

    sdk_headers = BaseResource._headers

    def _headers(self) -> dict[str, str]:
        return {**sdk_headers(self), **public_origin_headers()}

    BaseResource._headers = _headers
    sdk_attachments._requests = storage_requests
    mcp_attachments._requests = storage_requests
    _origin_installed = True


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
