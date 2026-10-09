"""FastMCP server factories for the supported transports."""

from __future__ import annotations

from fastmcp import FastMCP

from plane_mcp.auth import PlaneHeaderAuthProvider, ops_auth_provider
from plane_mcp.instructions import OPS_INSTRUCTIONS, SERVER_INSTRUCTIONS
from plane_mcp.middleware import PlaneLoggingMiddleware, PlaneToolVisibilityMiddleware
from plane_mcp.tools import hidden_discovery_tools, register_tools


def get_header_mcp():
    header_mcp = FastMCP(
        "Plane MCP Server (header-http)",
        instructions=SERVER_INSTRUCTIONS,
        auth=PlaneHeaderAuthProvider(
            required_scopes=["read", "write"],
        ),
    )
    header_mcp.add_middleware(PlaneLoggingMiddleware())
    register_tools(header_mcp)
    header_mcp.add_middleware(PlaneToolVisibilityMiddleware(hidden_discovery_tools()))
    return header_mcp


def get_ops_mcp():
    """Zil Ops: OAuth-protected endpoint (Ops is the authorization server)."""
    ops_mcp = FastMCP(
        "Zil Ops",
        instructions=SERVER_INSTRUCTIONS + OPS_INSTRUCTIONS,
        auth=ops_auth_provider(),
    )
    ops_mcp.add_middleware(PlaneLoggingMiddleware())
    register_tools(ops_mcp)
    ops_mcp.add_middleware(PlaneToolVisibilityMiddleware(hidden_discovery_tools()))
    return ops_mcp


def get_stdio_mcp():
    stdio_mcp = FastMCP(
        "Plane MCP Server (stdio)",
        instructions=SERVER_INSTRUCTIONS,
    )
    stdio_mcp.add_middleware(PlaneLoggingMiddleware())
    register_tools(stdio_mcp)
    stdio_mcp.add_middleware(PlaneToolVisibilityMiddleware(hidden_discovery_tools()))
    return stdio_mcp
