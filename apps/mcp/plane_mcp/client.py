"""Plane client initialization for MCP server."""

import os
from typing import NamedTuple

from fastmcp.server.auth.auth import AccessToken
from fastmcp.server.dependencies import get_access_token
from fastmcp.utilities.logging import get_logger
from plane import PlaneClient

logger = get_logger(__name__)


class PlaneClientContext(NamedTuple):
    """Context containing Plane client and workspace information."""

    client: PlaneClient
    workspace_slug: str


def get_plane_client_context() -> PlaneClientContext:
    """
    Initialize and return a PlaneClient instance with workspace context.

    Authentication is resolved from the MCP request context when available
    (PlaneHeaderAuthProvider: x-api-key + x-workspace-slug headers), otherwise
    from environment variables (stdio mode):
    1. Environment variables (PLANE_API_KEY + PLANE_WORKSPACE_SLUG)
    2. HTTP headers (x-api-key + x-workspace-slug)

    Environment variables:
    - PLANE_INTERNAL_BASE_URL: Internal URL for Plane API (preferred for server-to-server calls)
    - PLANE_BASE_URL: Base URL for Plane API (fallback, default: https://api.plane.so)

    Returns:
        PlaneClientContext containing configured PlaneClient instance and workspace slug

    Raises:
        ConfigurationError: If access token is not available or workspace slug is missing
    """
    base_url = os.getenv("PLANE_INTERNAL_BASE_URL") or os.getenv("PLANE_BASE_URL", "https://api.plane.so")
    workspace_slug = os.getenv("PLANE_WORKSPACE_SLUG", "")

    api_key = os.getenv("PLANE_API_KEY", "")

    # In HTTP mode the header auth provider validates x-api-key + x-workspace-slug
    # and attaches the token to the request context; stdio has no request
    # context and falls through to the environment variables above.
    stored_access_token: AccessToken | None = get_access_token()
    if stored_access_token:
        api_key = stored_access_token.token
        workspace_slug = stored_access_token.claims.get("workspace_slug", "") or workspace_slug

    client = PlaneClient(
        base_url=base_url,
        api_key=api_key,
    )

    return PlaneClientContext(
        client=client,
        workspace_slug=workspace_slug,
    )
