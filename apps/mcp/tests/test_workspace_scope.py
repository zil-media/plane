"""Zil Ops: a connection's main workspace, and the optional access to all the person's workspaces."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from fastmcp.server.auth.auth import AccessToken

from plane_mcp import workspace_scope
from plane_mcp.auth import ops_oauth
from plane_mcp.auth.ops_oauth import OpsTokenVerifier

WORKSPACES = [{"slug": "zil", "name": "Zil Global"}, {"slug": "meraki", "name": "Meraki"}]


@pytest.fixture()
def ops_env(monkeypatch):
    monkeypatch.setenv("OPS_PUBLIC_URL", "https://ops.example.com")
    monkeypatch.setenv("PLANE_INTERNAL_BASE_URL", "http://api:8000")
    monkeypatch.setenv("PLANE_MCP_EDITION", "community")
    monkeypatch.setenv("PLANE_API_KEY", "plane_api_k")
    monkeypatch.setenv("PLANE_WORKSPACE_SLUG", "zil")
    ops_oauth._cache.clear()


def connect_as(monkeypatch, *, main: str, all_workspaces: bool, workspaces: list[dict[str, str]] | None = None):
    usable = WORKSPACES if all_workspaces else [w for w in WORKSPACES if w["slug"] == main]
    token = AccessToken(
        token="plane_api_k",
        client_id="ops-user:u1",
        scopes=["mcp"],
        claims={"workspace_slug": main, "all_workspaces": all_workspaces, "workspaces": workspaces or usable},
    )
    monkeypatch.setattr(workspace_scope, "get_access_token", lambda: token)


class FakeResponse:
    status_code = 200
    content = b"x"

    def json(self):
        return {"changed": True, "summary": ["ok"], "blocks": ""}


def record_ops_calls(monkeypatch) -> list[str]:
    from plane_mcp import ops as ops_module

    urls: list[str] = []

    def fake_request(method, url, headers, timeout, **kwargs):
        urls.append(url)
        return FakeResponse()

    monkeypatch.setattr(ops_module.requests, "request", fake_request)
    return urls


def run(coro_fn):
    from plane_mcp.server import get_ops_mcp

    async def go():
        async with Client(get_ops_mcp()) as client:
            return await coro_fn(client)

    return asyncio.run(go())


EDIT = {"page_id": "p1", "project_id": "pr1", "ops": [{"op": "replace_text", "find": "a", "replace": "b"}]}


class TestDiscovery:
    def test_single_workspace_connection_advertises_no_workspace_argument(self, ops_env, monkeypatch):
        connect_as(monkeypatch, main="zil", all_workspaces=False)
        tools = {tool.name: tool for tool in run(lambda c: c.list_tools())}
        assert "list_workspaces" in tools
        assert "workspace" not in tools["edit_page"].input_schema["properties"]

    def test_all_workspaces_connection_adds_it_to_every_tool(self, ops_env, monkeypatch):
        connect_as(monkeypatch, main="zil", all_workspaces=True)
        tools = run(lambda c: c.list_tools())
        for tool in tools:
            has_arg = "workspace" in tool.input_schema.get("properties", {})
            assert has_arg == (tool.name != "list_workspaces"), tool.name
        edit = next(tool for tool in tools if tool.name == "edit_page")
        assert "workspace" not in edit.input_schema.get("required", [])

    def test_list_workspaces(self, ops_env, monkeypatch):
        connect_as(monkeypatch, main="zil", all_workspaces=True)
        result = run(lambda c: c.call_tool("list_workspaces", {}))
        assert result.data["main_workspace"] == "zil"
        assert result.data["all_workspaces"] is True
        assert [(w["slug"], w["main"]) for w in result.data["workspaces"]] == [("zil", True), ("meraki", False)]

        connect_as(monkeypatch, main="zil", all_workspaces=False)
        result = run(lambda c: c.call_tool("list_workspaces", {}))
        assert [w["slug"] for w in result.data["workspaces"]] == ["zil"]


class TestCalls:
    def test_without_workspace_uses_the_main_one(self, ops_env, monkeypatch):
        connect_as(monkeypatch, main="zil", all_workspaces=True)
        urls = record_ops_calls(monkeypatch)
        run(lambda c: c.call_tool("edit_page", EDIT))
        assert urls == ["http://api:8000/api/v1/workspaces/zil/projects/pr1/pages/p1/edit/"]

    def test_workspace_argument_routes_the_call(self, ops_env, monkeypatch):
        connect_as(monkeypatch, main="zil", all_workspaces=True)
        urls = record_ops_calls(monkeypatch)
        run(lambda c: c.call_tool("edit_page", {**EDIT, "workspace": "meraki"}))
        assert urls == ["http://api:8000/api/v1/workspaces/meraki/projects/pr1/pages/p1/edit/"]

    def test_unknown_workspace_is_refused(self, ops_env, monkeypatch):
        connect_as(monkeypatch, main="zil", all_workspaces=True)
        urls = record_ops_calls(monkeypatch)
        with pytest.raises(ToolError, match="Unknown workspace 'vibra'"):
            run(lambda c: c.call_tool("edit_page", {**EDIT, "workspace": "vibra"}))
        assert urls == []

    def test_single_workspace_connection_cannot_switch(self, ops_env, monkeypatch):
        connect_as(monkeypatch, main="zil", all_workspaces=False)
        urls = record_ops_calls(monkeypatch)
        with pytest.raises(ToolError, match="only has access to the workspace 'zil'"):
            run(lambda c: c.call_tool("edit_page", {**EDIT, "workspace": "meraki"}))
        assert urls == []
        # naming the main workspace explicitly is fine
        run(lambda c: c.call_tool("edit_page", {**EDIT, "workspace": "zil"}))
        assert urls == ["http://api:8000/api/v1/workspaces/zil/projects/pr1/pages/p1/edit/"]

    def test_no_main_workspace_asks_for_one(self, ops_env, monkeypatch):
        connect_as(monkeypatch, main="", all_workspaces=True)
        with pytest.raises(ToolError, match="pass `workspace`"):
            run(lambda c: c.call_tool("edit_page", EDIT))


class TestVerifierClaims:
    def _verify(self, monkeypatch, body: dict[str, Any]) -> AccessToken:
        class FakeAsyncClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def get(self, url, headers):
                return type("R", (), {"status_code": 200, "json": lambda self: body})()

        monkeypatch.setattr(ops_oauth.httpx, "AsyncClient", FakeAsyncClient)
        return asyncio.run(OpsTokenVerifier().verify_token("plane_api_v"))

    def test_single_workspace_grant_only_exposes_its_workspace(self, ops_env, monkeypatch):
        token = self._verify(
            monkeypatch,
            {"user": {"id": "u1"}, "workspace_slug": "meraki", "all_workspaces": False, "workspaces": WORKSPACES},
        )
        assert token.claims["all_workspaces"] is False
        assert token.claims["workspaces"] == [{"slug": "meraki", "name": "Meraki"}]

    def test_all_workspaces_grant_exposes_every_workspace(self, ops_env, monkeypatch):
        token = self._verify(
            monkeypatch,
            {"user": {"id": "u1"}, "workspace_slug": "meraki", "all_workspaces": True, "workspaces": WORKSPACES},
        )
        assert token.claims["workspace_slug"] == "meraki"
        assert token.claims["all_workspaces"] is True
        assert token.claims["workspaces"] == WORKSPACES
