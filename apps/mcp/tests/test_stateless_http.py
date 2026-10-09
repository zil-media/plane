"""Tests for stateless HTTP mode.

Verifies that the header HTTP app works correctly with stateless_http=True,
which prevents unbounded session accumulation in
StreamableHTTPSessionManager._server_instances.
"""

import pytest
from fastmcp import FastMCP
from starlette.testclient import TestClient

from plane_mcp.auth import PlaneHeaderAuthProvider


@pytest.fixture()
def header_mcp():
    """Build a header-auth MCP server."""
    return FastMCP(
        "Plane MCP Server (header-http)",
        auth=PlaneHeaderAuthProvider(
            required_scopes=["read", "write"],
        ),
    )


class TestStatelessHttpHeader:
    """Verify header-auth HTTP app works in stateless mode."""

    def test_header_app_creates_with_stateless_flag(self, header_mcp):
        """http_app(stateless_http=True) should return a valid ASGI app."""
        app = header_mcp.http_app(stateless_http=True)
        assert app is not None

    def test_header_mcp_endpoint_responds(self, header_mcp):
        """The /mcp endpoint should accept POST requests in stateless mode."""
        app = header_mcp.http_app(stateless_http=True)
        client = TestClient(app, raise_server_exceptions=False)
        response = client.post("/mcp", json={"jsonrpc": "2.0", "method": "initialize", "id": 1})
        # Without auth headers, expect 401/403, not 500
        assert response.status_code in (401, 403)
