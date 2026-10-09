"""Unit tests for the thin Cloud/CE page backend boundary."""

from types import SimpleNamespace

from plane.models.pages import CreatePage, Page, UpdatePage

from plane_mcp.page_backends import CloudPageBackend


class _Pages:
    def __init__(self):
        self.calls = []

    def update_project_page(self, workspace_slug, project_id, page_id, data):
        self.calls.append((workspace_slug, project_id, page_id, data))
        return Page(id=page_id, name=data.name, description_html=data.description_html)

    def create_project_page(self, workspace_slug, project_id, data):
        self.calls.append((workspace_slug, project_id, data))
        return Page(id="page-1", name=data.name)


def test_cloud_update_uses_one_sdk_request_for_name_and_content():
    pages = _Pages()
    backend = CloudPageBackend(SimpleNamespace(pages=pages), "space")

    page = backend.update_page("page-1", "project-1", UpdatePage(name="renamed", description_html="<p>new</p>"))

    assert page.id == "page-1"
    assert page.name == "renamed"
    assert page.description_html == "<p>new</p>"
    assert len(pages.calls) == 1
    _, project_id, page_id, data = pages.calls[0]
    assert (project_id, page_id) == ("project-1", "page-1")
    assert data.model_dump(exclude_none=True) == {"name": "renamed", "description_html": "<p>new</p>"}


def test_cloud_create_passes_hierarchy_fields_to_the_sdk():
    pages = _Pages()
    backend = CloudPageBackend(SimpleNamespace(pages=pages), "space")

    backend.create_page(
        CreatePage(name="child", description_html="<p>x</p>", parent_id="parent-1", collection_id="collection-1"),
        "project-1",
    )

    _, project_id, data = pages.calls[0]
    assert project_id == "project-1"
    assert data.parent_id == "parent-1"
    assert data.collection_id == "collection-1"
