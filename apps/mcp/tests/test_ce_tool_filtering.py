"""Tool-discovery tests for Plane Community Edition mode."""

import asyncio
import json
from pathlib import Path

import pytest

from plane_mcp.server import get_stdio_mcp
from plane_mcp.tools import (
    CE_SESSION_TOOLS,
    CE_UNAVAILABLE_TOOLS,
    PAGE_ALIAS_TOOLS,
    PAGE_RESOURCE_TOOL,
)

_SNAPSHOT = Path(__file__).with_name("tool_surface_snapshot.json")


@pytest.fixture(autouse=True)
def _clear_session_env(monkeypatch):
    """Default every test to *no* app-session credentials configured."""
    for var in ("PLANE_SESSION_EMAIL", "PLANE_SESSION_PASSWORD", "PLANE_SESSION_COOKIE"):
        monkeypatch.delenv(var, raising=False)


def _discovery() -> set[str]:
    """Tool names as a client sees them (discovery, hidden aliases filtered)."""
    mcp = get_stdio_mcp()
    return {tool.name for tool in asyncio.run(mcp.list_tools())}


def _registered(name: str):
    """A registered tool by name, ignoring the visibility middleware."""
    mcp = get_stdio_mcp()
    return next(tool for tool in asyncio.run(mcp.list_tools(run_middleware=False)) if tool.name == name)


def _required(name: str) -> list[str]:
    return sorted(_registered(name).parameters.get("required") or [])


def _surface(edition: str, monkeypatch) -> dict[str, list[str]]:
    monkeypatch.setenv("PLANE_MCP_EDITION", edition)
    mcp = get_stdio_mcp()
    tools = asyncio.run(mcp.list_tools())
    return {tool.name: sorted(tool.parameters.get("required") or []) for tool in tools}


def test_community_mode_hides_unavailable_tools(monkeypatch):
    monkeypatch.setenv("PLANE_MCP_EDITION", "community")

    tool_names = _discovery()

    assert not tool_names & CE_UNAVAILABLE_TOOLS
    assert "list_projects" in tool_names
    assert "list_work_item_activities" in tool_names
    assert "create_work_item_relation" in tool_names


def test_community_mode_hides_session_tools_without_credentials(monkeypatch):
    monkeypatch.setenv("PLANE_MCP_EDITION", "community")

    tool_names = _discovery()

    assert not tool_names & CE_SESSION_TOOLS
    # All page operations are session-only on CE: the resource tool is hidden too.
    assert PAGE_RESOURCE_TOOL not in tool_names


def test_community_mode_exposes_page_resource_with_credentials(monkeypatch):
    monkeypatch.setenv("PLANE_MCP_EDITION", "community")
    monkeypatch.setenv("PLANE_SESSION_EMAIL", "admin@example.test")
    monkeypatch.setenv("PLANE_SESSION_PASSWORD", "secret")

    tool_names = _discovery()

    assert CE_SESSION_TOOLS <= tool_names
    assert PAGE_RESOURCE_TOOL in tool_names
    # The per-operation names stay compatibility aliases: callable, undiscoverable.
    assert not tool_names & PAGE_ALIAS_TOOLS


def test_cloud_mode_keeps_full_tool_surface(monkeypatch):
    monkeypatch.setenv("PLANE_MCP_EDITION", "cloud")

    tool_names = _discovery()

    assert CE_UNAVAILABLE_TOOLS <= tool_names
    assert CE_SESSION_TOOLS <= tool_names
    assert PAGE_RESOURCE_TOOL in tool_names
    assert not tool_names & PAGE_ALIAS_TOOLS


def test_page_aliases_remain_registered_with_compatible_signatures(monkeypatch):
    monkeypatch.setenv("PLANE_MCP_EDITION", "cloud")

    assert _required("update_page") == ["page_id", "project_id"]
    assert _required("update_page_content") == ["description_html", "page_id", "project_id"]
    assert _required("archive_page") == ["page_id", "project_id"]


def test_page_resource_tool_only_requires_action(monkeypatch):
    monkeypatch.setenv("PLANE_MCP_EDITION", "cloud")

    tool = _registered(PAGE_RESOURCE_TOOL)

    assert tool.parameters.get("required") == ["action"]
    assert {
        "page_id",
        "project_id",
        "name",
        "description_html",
        "parent_id",
        "collection_id",
    } <= set(tool.parameters["properties"])


def test_tool_surface_snapshot(monkeypatch):
    """Lock tool names and required parameters for both editions.

    Update tests/tool_surface_snapshot.json deliberately when a signature
    changes; silent drift fails here.
    """
    snapshot = json.loads(_SNAPSHOT.read_text())

    assert _surface("community", monkeypatch) == snapshot["community"]
    assert _surface("cloud", monkeypatch) == snapshot["cloud"]


def test_auto_mode_detects_a_self_hosted_url(monkeypatch):
    monkeypatch.setenv("PLANE_MCP_EDITION", "auto")
    monkeypatch.delenv("PLANE_INTERNAL_BASE_URL", raising=False)
    monkeypatch.setenv("PLANE_BASE_URL", "https://plane.example.test")

    tool_names = _discovery()

    assert not tool_names & CE_UNAVAILABLE_TOOLS


def test_community_mode_does_not_advertise_unsupported_pql(monkeypatch):
    monkeypatch.setenv("PLANE_MCP_EDITION", "community")

    assert "pql" not in _registered("list_work_items").parameters["properties"]


def test_cloud_mode_keeps_pql(monkeypatch):
    monkeypatch.setenv("PLANE_MCP_EDITION", "cloud")

    assert "pql" in _registered("list_work_items").parameters["properties"]
