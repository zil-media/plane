"""Unit tests for CE Pages mutations and the page(action=...) resource tool."""

import asyncio

from fastmcp import FastMCP
from plane.errors.errors import HttpError

from plane_mcp import page_backends
from plane_mcp.tools import pages


class _AppSession:
    def __init__(self):
        self.calls = []

    def get(self, path, **kwargs):
        self.calls.append(("get", path, kwargs))
        page = {"id": "page-1", "name": "saved", "description_html": "<p>saved</p>"}
        if path.endswith("pages/"):
            return [page]
        return page

    def post(self, path, **kwargs):
        self.calls.append(("post", path, kwargs))
        if path.endswith("pages/"):
            return {"id": "page-1"}
        return {"archived_at": "2026-09-03T00:00:00Z"}

    def patch(self, path, **kwargs):
        self.calls.append(("patch", path, kwargs))
        if path.endswith("description/"):
            return {"message": "updated"}
        return {"id": "page-1", "name": "renamed"}

    def delete(self, path, **kwargs):
        self.calls.append(("delete", path, kwargs))


def _tools(monkeypatch):
    app = _AppSession()
    monkeypatch.setattr(page_backends, "is_community_edition", lambda: True)
    monkeypatch.setattr(page_backends, "session_auth_available", lambda: True)
    monkeypatch.setattr(page_backends, "get_app_session", lambda: app)
    monkeypatch.setattr(pages, "get_plane_client_context", lambda: (object(), "space"))
    mcp = FastMCP("test")
    pages.register_page_tools(mcp)
    tools = {tool.name: tool.fn for tool in asyncio.run(mcp.list_tools())}
    return app, tools


def test_create_page_persists_ce_content(monkeypatch):
    app, tools = _tools(monkeypatch)

    page = tools["create_page"]("title", "<p>body</p>", project_id="project-1")

    assert page.id == "page-1"
    assert app.calls == [
        ("post", "workspaces/space/projects/project-1/pages/", {"json": {"name": "title"}}),
        (
            "patch",
            "workspaces/space/projects/project-1/pages/page-1/description/",
            {"json": {"description_html": "<p>body</p>"}},
        ),
        ("get", "workspaces/space/projects/project-1/pages/page-1/", {}),
    ]


def test_create_page_reports_page_id_when_content_update_fails(monkeypatch):
    app, tools = _tools(monkeypatch)
    app.patch = lambda *args, **kwargs: (_ for _ in ()).throw(HttpError("bad HTML", 422, {}))

    try:
        tools["create_page"]("title", "<p>body</p>", project_id="project-1")
    except HttpError as exc:
        assert "page-1" in str(exc)
    else:
        raise AssertionError("expected content update failure")


def test_ce_page_mutations_use_proven_routes(monkeypatch):
    app, tools = _tools(monkeypatch)

    tools["update_page"]("page-1", "project-1", name="renamed")
    tools["update_page_content"]("page-1", "<p>new</p>", "project-1")
    tools["archive_page"]("page-1", "project-1")
    tools["unarchive_page"]("page-1", "project-1")
    tools["delete_page"]("page-1", "project-1")

    assert app.calls == [
        ("patch", "workspaces/space/projects/project-1/pages/page-1/", {"json": {"name": "renamed"}}),
        ("get", "workspaces/space/projects/project-1/pages/page-1/", {}),
        (
            "patch",
            "workspaces/space/projects/project-1/pages/page-1/description/",
            {"json": {"description_html": "<p>new</p>"}},
        ),
        ("get", "workspaces/space/projects/project-1/pages/page-1/", {}),
        ("post", "workspaces/space/projects/project-1/pages/page-1/archive/", {"json": {}}),
        ("get", "workspaces/space/projects/project-1/pages/page-1/", {}),
        ("delete", "workspaces/space/projects/project-1/pages/page-1/archive/", {}),
        ("get", "workspaces/space/projects/project-1/pages/page-1/", {}),
        ("delete", "workspaces/space/projects/project-1/pages/page-1/", {}),
    ]


def test_update_page_rejects_an_empty_update_before_calling_backend(monkeypatch):
    app, tools = _tools(monkeypatch)

    try:
        tools["update_page"]("page-1", "project-1")
    except ValueError as exc:
        assert "name and/or description_html" in str(exc)
    else:
        raise AssertionError("expected empty update to be rejected")

    assert app.calls == []


def test_update_reports_not_updated_when_name_absent_and_content_fails(monkeypatch):
    app, tools = _tools(monkeypatch)
    app.patch = lambda path, **kwargs: (
        (_ for _ in ()).throw(HttpError("bad HTML", 422, {})) if path.endswith("description/") else None
    )

    try:
        tools["update_page"]("page-1", "project-1", description_html="<p>x</p>")
    except HttpError as exc:
        assert "was not updated" in str(exc)
        assert "partially" not in str(exc)
    else:
        raise AssertionError("expected content update failure")


def test_update_reports_partial_state_when_name_succeeded_and_content_fails(monkeypatch):
    app, tools = _tools(monkeypatch)
    app.patch = lambda path, **kwargs: (
        (_ for _ in ()).throw(HttpError("bad HTML", 422, {}))
        if path.endswith("description/")
        else app.calls.append(("patch", path, kwargs))
    )

    try:
        tools["update_page"]("page-1", "project-1", name="renamed", description_html="<p>x</p>")
    except HttpError as exc:
        assert "only partially updated (name)" in str(exc)
    else:
        raise AssertionError("expected content update failure")


def test_ce_create_rejects_unverified_hierarchy_before_calling_app(monkeypatch):
    app, tools = _tools(monkeypatch)

    try:
        tools["create_page"]("title", "<p>body</p>", project_id="project-1", parent_id="parent-1")
    except ValueError as exc:
        assert "Nested pages" in str(exc)
    else:
        raise AssertionError("expected unverified CE hierarchy to be rejected")

    assert app.calls == []


def test_ce_create_forwards_hierarchy_when_capability_override_enabled(monkeypatch):
    app, tools = _tools(monkeypatch)
    monkeypatch.setenv("PLANE_CE_CAPABILITIES", "pages.parent_id")

    tools["create_page"]("title", "<p>body</p>", project_id="project-1", parent_id="parent-1")

    expected_post = (
        "post",
        "workspaces/space/projects/project-1/pages/",
        {"json": {"name": "title", "parent_id": "parent-1"}},
    )
    assert expected_post in app.calls


def test_page_action_dispatches_ce_routes(monkeypatch):
    app, tools = _tools(monkeypatch)

    tools["page"]("list", project_id="project-1")
    tools["page"]("retrieve", page_id="page-1", project_id="project-1")
    tools["page"]("create", name="title", description_html="<p>body</p>", project_id="project-1")
    tools["page"]("update", page_id="page-1", project_id="project-1", name="renamed", description_html="<p>x</p>")
    tools["page"]("archive", page_id="page-1", project_id="project-1")
    tools["page"]("unarchive", page_id="page-1", project_id="project-1")
    tools["page"]("delete", page_id="page-1", project_id="project-1")

    methods = [call[0] for call in app.calls]
    assert methods == [
        "get",  # list
        "get",  # retrieve
        "post",
        "patch",
        "get",  # create (metadata, content, read back)
        "patch",
        "patch",
        "get",  # update (name, content, read back)
        "post",
        "get",  # archive
        "delete",
        "get",  # unarchive
        "delete",  # delete
    ]


def test_page_action_validates_before_any_request(monkeypatch):
    app, tools = _tools(monkeypatch)

    for bad_args in (
        {"action": "explode", "project_id": "project-1"},
        {"action": "retrieve", "project_id": "project-1"},
        {"action": "update", "page_id": "page-1", "project_id": "project-1"},
    ):
        try:
            tools["page"](**bad_args)
        except ValueError:
            pass
        else:
            raise AssertionError(f"expected rejection for {bad_args}")

    assert app.calls == []


def test_ce_without_session_fails_fast_with_clear_error(monkeypatch):
    monkeypatch.setattr(page_backends, "is_community_edition", lambda: True)
    monkeypatch.setattr(page_backends, "session_auth_available", lambda: False)
    monkeypatch.setattr(pages, "get_plane_client_context", lambda: (object(), "space"))
    mcp = FastMCP("test")
    pages.register_page_tools(mcp)
    tools = {tool.name: tool.fn for tool in asyncio.run(mcp.list_tools())}

    calls = {
        "page": lambda: tools["page"]("list", project_id="project-1"),
        "update_page": lambda: tools["update_page"]("page-1", "project-1", name="x"),
        "list_pages": lambda: tools["list_pages"](project_id="project-1"),
    }
    for tool_name, call in calls.items():
        try:
            call()
        except ValueError as exc:
            assert "app-session credentials" in str(exc)
        else:
            raise AssertionError(f"expected session error from {tool_name}")
