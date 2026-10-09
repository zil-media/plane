"""Zil Ops patches: OAuth-protected /mcp, the Ops token check, and the page backend/tools."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastmcp import Client
from plane import PlaneClient
from plane.models.pages import CreatePage, UpdatePage
from starlette.testclient import TestClient

from plane_mcp.auth import ops_oauth
from plane_mcp.auth.ops_oauth import OpsTokenVerifier

PUBLIC = "https://ops.example.com"


@pytest.fixture()
def ops_env(monkeypatch):
    monkeypatch.setenv("OPS_LIVE_URL", "http://live:3000/live")
    monkeypatch.setenv("OPS_PUBLIC_URL", PUBLIC)
    monkeypatch.setenv("PLANE_INTERNAL_BASE_URL", "http://api:8000")
    monkeypatch.setenv("PLANE_MCP_EDITION", "community")
    ops_oauth._cache.clear()


class FakeResponse:
    def __init__(self, status_code: int, body: Any = None):
        self.status_code = status_code
        self._body = body
        self.content = b"x" if body is not None else b""
        self.text = str(body)
        self.reason = "reason"

    def json(self):
        return self._body


class TestOAuthEndpoint:
    def test_advertises_ops_as_authorization_server(self, ops_env):
        from plane_mcp.__main__ import build_http_app

        client = TestClient(build_http_app(), raise_server_exceptions=False)
        metadata = client.get("/.well-known/oauth-protected-resource/mcp")
        assert metadata.status_code == 200
        body = metadata.json()
        assert body["resource"] == f"{PUBLIC}/mcp"
        assert body["authorization_servers"] == [PUBLIC]

    def test_unauthenticated_call_gets_the_discovery_challenge(self, ops_env):
        from plane_mcp.__main__ import build_http_app

        client = TestClient(build_http_app(), raise_server_exceptions=False)
        response = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "initialize", "id": 1},
            headers={"Accept": "application/json, text/event-stream"},
        )
        assert response.status_code == 401
        assert "resource_metadata" in response.headers["www-authenticate"]
        assert f"{PUBLIC}/.well-known/oauth-protected-resource/mcp" in response.headers["www-authenticate"]

    def test_pat_endpoint_still_mounted(self, ops_env):
        from plane_mcp.__main__ import build_http_app

        client = TestClient(build_http_app(), raise_server_exceptions=False)
        response = client.post("/http/api-key/mcp", json={"jsonrpc": "2.0", "method": "initialize", "id": 1})
        assert response.status_code in (401, 403)


class TestOpsTokenVerifier:
    def _patch(self, monkeypatch, status: int, body: dict | None, calls: list):
        class FakeAsyncClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def get(self, url, headers):
                calls.append((url, headers))
                return FakeResponse(status, body)

        monkeypatch.setattr(ops_oauth.httpx, "AsyncClient", FakeAsyncClient)

    def test_token_workspace_and_cache(self, ops_env, monkeypatch):
        calls: list = []
        self._patch(
            monkeypatch,
            200,
            {"user": {"id": "u1", "email": "a@zil.global"}, "workspace_slug": "zil", "workspaces": []},
            calls,
        )
        verifier = OpsTokenVerifier()
        token = asyncio.run(verifier.verify_token("plane_api_x"))
        assert token.claims["workspace_slug"] == "zil"
        assert calls[0] == ("http://api:8000/api/v1/zil-mcp/whoami/", {"X-Api-Key": "plane_api_x"})
        asyncio.run(verifier.verify_token("plane_api_x"))
        assert len(calls) == 1

    def test_personal_token_uses_the_only_workspace(self, ops_env, monkeypatch):
        self._patch(
            monkeypatch,
            200,
            {"user": {"id": "u1"}, "workspace_slug": None, "workspaces": [{"slug": "only", "name": "Only"}]},
            [],
        )
        token = asyncio.run(OpsTokenVerifier().verify_token("plane_api_y"))
        assert token.claims["workspace_slug"] == "only"

    def test_rejected_token(self, ops_env, monkeypatch):
        self._patch(monkeypatch, 401, {"detail": "no"}, [])
        assert asyncio.run(OpsTokenVerifier().verify_token("plane_api_z")) is None


class TestOpsTools:
    def test_page_tools_are_discoverable(self, ops_env):
        from plane_mcp.server import get_stdio_mcp

        async def names():
            async with Client(get_stdio_mcp()) as client:
                return {tool.name for tool in await client.list_tools()}

        tools = asyncio.run(names())
        assert {"page", "read_page", "edit_page", "search_pages"} <= tools
        assert "update_page" not in tools  # aliases stay hidden

    def test_edit_page_posts_ops_to_live(self, ops_env, monkeypatch):
        from plane_mcp import ops as ops_module
        from plane_mcp.server import get_stdio_mcp

        monkeypatch.setenv("PLANE_API_KEY", "plane_api_k")
        monkeypatch.setenv("PLANE_WORKSPACE_SLUG", "zil")
        calls: list = []

        def fake_request(method, url, headers, timeout, **kwargs):
            calls.append((method, url, headers, kwargs))
            return FakeResponse(200, {"changed": True, "summary": ["ok"], "blocks": ""})

        monkeypatch.setattr(ops_module.requests, "request", fake_request)

        async def call():
            async with Client(get_stdio_mcp()) as client:
                return await client.call_tool(
                    "edit_page",
                    {
                        "page_id": "p1",
                        "project_id": "pr1",
                        "ops": [{"op": "replace_text", "find": "a", "replace": "b"}],
                    },
                )

        asyncio.run(call())
        method, url, headers, kwargs = calls[0]
        assert (method, url) == ("POST", "http://live:3000/live/agent/pages/p1/edit")
        assert headers == {"X-Api-Key": "plane_api_k"}
        assert kwargs["json"] == {
            "workspace_slug": "zil",
            "project_id": "pr1",
            "ops": [{"op": "replace_text", "find": "a", "replace": "b"}],
        }


class TestOpsPageBackend:
    def _backend(self, monkeypatch, responses: dict[tuple[str, str], Any], calls: list):
        from plane_mcp import ops as ops_module
        from plane_mcp.page_backends import get_page_backend

        def fake_request(method, url, headers, timeout, **kwargs):
            calls.append((method, url, kwargs.get("json")))
            for (m, suffix), body in responses.items():
                if m == method and url.endswith(suffix):
                    return FakeResponse(200, body)
            return FakeResponse(200, {"id": "p1", "name": "Plan", "parent": None})

        monkeypatch.setattr(ops_module.requests, "request", fake_request)
        return get_page_backend(PlaneClient(base_url="http://api:8000", api_key="plane_api_k"), "zil")

    def test_create_writes_content_through_live(self, ops_env, monkeypatch):
        calls: list = []
        backend = self._backend(monkeypatch, {("POST", "/projects/pr1/pages/"): {"id": "p1"}}, calls)
        page = backend.create_page(CreatePage(name="Plan", description_html="# Hola", parent_id="parent-1"), "pr1")
        assert page.id == "p1"
        assert calls[0] == (
            "POST",
            "http://api:8000/api/v1/workspaces/zil/projects/pr1/pages/",
            {"name": "Plan", "parent": "parent-1"},
        )
        assert calls[1] == (
            "POST",
            "http://live:3000/live/agent/pages/p1/edit",
            {"workspace_slug": "zil", "project_id": "pr1", "ops": [{"op": "replace_all", "content": "# Hola"}]},
        )

    def test_rename_goes_through_the_document_title(self, ops_env, monkeypatch):
        calls: list = []
        backend = self._backend(monkeypatch, {}, calls)
        backend.update_page("p1", "pr1", UpdatePage(name="Nuevo"))
        assert calls[0] == (
            "POST",
            "http://live:3000/live/agent/pages/p1/rename",
            {"workspace_slug": "zil", "project_id": "pr1", "name": "Nuevo"},
        )

    def test_requires_project(self, ops_env, monkeypatch):
        backend = self._backend(monkeypatch, {}, [])
        with pytest.raises(ValueError, match="project_id"):
            backend.list_pages(None, None)
