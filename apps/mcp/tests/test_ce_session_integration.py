"""Live integration tests for CE app-session routing (archive + project pages).

Skipped unless a local CE stack is reachable *and* app-session credentials are
configured. Enable by exporting (see TESTING_LOCAL.md):

    PLANE_TEST_API_KEY, PLANE_TEST_WORKSPACE_SLUG, PLANE_BASE_URL,
    PLANE_SESSION_EMAIL + PLANE_SESSION_PASSWORD   (or PLANE_SESSION_COOKIE)

These exercise the app API through the in-memory stdio MCP, creating and then
cleaning up their own throwaway resources.
"""

import asyncio
import os
import uuid

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from plane_mcp.app_session import session_auth_available

_ARCHIVE_REQUIRED = ("PLANE_TEST_API_KEY", "PLANE_TEST_WORKSPACE_SLUG", "PLANE_BASE_URL")
_PAGES_REQUIRED = ("PLANE_TEST_WORKSPACE_SLUG", "PLANE_BASE_URL", "PLANE_TEST_PROJECT_ID")


def _has_live_config(*variables: str) -> bool:
    return session_auth_available() and all(os.getenv(variable) for variable in variables)


@pytest.fixture
def ce_env(monkeypatch):
    """Run the in-memory server in CE mode with PAT + session creds wired up."""
    monkeypatch.setenv("PLANE_MCP_EDITION", "community")
    monkeypatch.setenv("PLANE_API_KEY", os.getenv("PLANE_TEST_API_KEY", "session-only"))
    monkeypatch.setenv("PLANE_WORKSPACE_SLUG", os.environ["PLANE_TEST_WORKSPACE_SLUG"])
    from plane_mcp import app_session

    app_session.reset_app_session()
    yield
    app_session.reset_app_session()


def _val(result):
    return result.data


def _rows(payload):
    """Normalize a list/dict/paginated-model tool result into a list of items."""
    if isinstance(payload, list):
        return payload
    results = payload.get("results") if isinstance(payload, dict) else getattr(payload, "results", None)
    return results if results is not None else payload


def _id(item):
    return item["id"] if isinstance(item, dict) else item.id


def _field(item, name):
    return item.get(name) if isinstance(item, dict) else getattr(item, name)


def _first_project_id(projects) -> str:
    return _id(_rows(projects)[0])


async def _archive_roundtrip():
    from plane_mcp.server import get_stdio_mcp

    async with Client(get_stdio_mcp()) as client:
        names = {t.name for t in await client.list_tools()}
        assert "manage_work_item_archive" in names  # exposed because creds are set

        project_id = _first_project_id(_val(await client.call_tool("list_projects", {})))

        # States: find a cancelled/completed one (only those can be archived).
        states = _rows(_val(await client.call_tool("list_states", {"project_id": project_id})))
        closable = next(s for s in states if _field(s, "group") in ("completed", "cancelled"))
        state_id = _id(closable)

        created = _val(
            await client.call_tool(
                "create_work_item", {"project_id": project_id, "name": f"itest-archive-{uuid.uuid4().hex[:8]}"}
            )
        )
        wid = _id(created)
        try:
            await client.call_tool(
                "update_work_item", {"project_id": project_id, "work_item_id": wid, "state": state_id}
            )
            await client.call_tool(
                "manage_work_item_archive", {"project_id": project_id, "work_item_id": wid, "archive": True}
            )
            listed = _val(await client.call_tool("list_archived_work_items", {"project_id": project_id}))
            assert wid in [_id(i) for i in _rows(listed)]
            await client.call_tool(
                "manage_work_item_archive", {"project_id": project_id, "work_item_id": wid, "archive": False}
            )
        finally:
            await client.call_tool("delete_work_item", {"project_id": project_id, "work_item_id": wid})


async def _pages_roundtrip():
    from plane_mcp.app_session import get_app_session
    from plane_mcp.server import get_stdio_mcp

    async with Client(get_stdio_mcp()) as client:
        names = {t.name for t in await client.list_tools()}
        assert {"list_pages", "create_page", "retrieve_page"} <= names

        project_id = os.environ["PLANE_TEST_PROJECT_ID"]
        page = _val(
            await client.call_tool(
                "create_page",
                {
                    "name": f"itest-page-{uuid.uuid4().hex[:8]}",
                    "description_html": "<p>x</p>",
                    "project_id": project_id,
                },
            )
        )
        page_id = _id(page)
        try:
            assert _field(page, "description_html") == "<p>x</p>"
            pages = _rows(_val(await client.call_tool("list_pages", {"project_id": project_id})))
            assert page_id in [_id(p) for p in pages]

            fetched = _val(await client.call_tool("retrieve_page", {"page_id": page_id, "project_id": project_id}))
            assert _id(fetched) == page_id

            updated = _val(
                await client.call_tool(
                    "update_page", {"page_id": page_id, "name": "itest-page-updated", "project_id": project_id}
                )
            )
            assert _field(updated, "name") == "itest-page-updated"

            content = _val(
                await client.call_tool(
                    "update_page_content",
                    {"page_id": page_id, "description_html": "<p>updated</p>", "project_id": project_id},
                )
            )
            assert _field(content, "description_html") == "<p>updated</p>"

            archived = _val(await client.call_tool("archive_page", {"page_id": page_id, "project_id": project_id}))
            assert _field(archived, "archived_at")
            unarchived = _val(await client.call_tool("unarchive_page", {"page_id": page_id, "project_id": project_id}))
            assert _field(unarchived, "archived_at") is None

            # Workspace-scope must fail cleanly on CE.
            with pytest.raises(ToolError, match="Workspace-level pages"):
                await client.call_tool("list_pages", {})
        finally:
            ws = os.environ["PLANE_TEST_WORKSPACE_SLUG"]
            app = get_app_session()
            app.post(f"workspaces/{ws}/projects/{project_id}/pages/{page_id}/archive/", json={})
            await client.call_tool("delete_page", {"page_id": page_id, "project_id": project_id})


@pytest.mark.skipif(not _has_live_config(*_ARCHIVE_REQUIRED), reason="requires live CE + PAT + session credentials")
def test_ce_session_archive_roundtrip(ce_env):
    asyncio.run(_archive_roundtrip())


@pytest.mark.skipif(
    not _has_live_config(*_PAGES_REQUIRED), reason="requires live CE Pages configuration + session credentials"
)
def test_ce_session_pages_roundtrip(ce_env):
    asyncio.run(_pages_roundtrip())
