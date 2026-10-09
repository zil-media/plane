"""Page backends for Plane Cloud and Community Edition.

The public SDK and CE's session-authenticated app API expose different page
routes.  Keep that difference below the MCP tool layer while retaining the SDK
``Page`` model as the one return type.
"""

from __future__ import annotations

from typing import Any, Protocol

from plane import PlaneClient
from plane.errors.errors import HttpError
from plane.models.pages import CreatePage, Page, UpdatePage

from plane_mcp.app_session import (
    get_app_session,
    is_community_edition,
    session_auth_available,
)
from plane_mcp.ce_capabilities import PAGES_COLLECTION_ID, PAGES_PARENT_ID, ce_capabilities
from plane_mcp.ops import OpsSession, ops_enabled


class PageBackend(Protocol):
    """Thin page-operation boundary; implementations return SDK models."""

    def list_pages(self, project_id: str | None, params: dict[str, Any] | None) -> list[Page]: ...

    def retrieve_page(self, page_id: str, project_id: str | None) -> Page: ...

    def create_page(self, data: CreatePage, project_id: str | None) -> Page: ...

    def update_page(self, page_id: str, project_id: str, data: UpdatePage) -> Page: ...

    def archive_page(self, page_id: str, project_id: str) -> Page: ...

    def unarchive_page(self, page_id: str, project_id: str) -> Page: ...

    def delete_page(self, page_id: str, project_id: str) -> None: ...


class CloudPageBackend:
    """Public ``/api/v1`` page operations supplied by ``plane-sdk``."""

    def __init__(self, client: PlaneClient, workspace_slug: str):
        self.client = client
        self.workspace_slug = workspace_slug

    def list_pages(self, project_id: str | None, params: dict[str, Any] | None) -> list[Page]:
        if project_id is None:
            return self.client.pages.list_workspace_pages(self.workspace_slug, params=params).results
        return self.client.pages.list_project_pages(self.workspace_slug, project_id, params=params).results

    def retrieve_page(self, page_id: str, project_id: str | None) -> Page:
        if project_id is None:
            return self.client.pages.retrieve_workspace_page(self.workspace_slug, page_id)
        return self.client.pages.retrieve_project_page(self.workspace_slug, project_id, page_id)

    def create_page(self, data: CreatePage, project_id: str | None) -> Page:
        if project_id is None:
            return self.client.pages.create_workspace_page(self.workspace_slug, data)
        return self.client.pages.create_project_page(self.workspace_slug, project_id, data)

    def update_page(self, page_id: str, project_id: str, data: UpdatePage) -> Page:
        return self.client.pages.update_project_page(self.workspace_slug, project_id, page_id, data)

    def archive_page(self, page_id: str, project_id: str) -> Page:
        self.client.pages.archive_project_page(self.workspace_slug, project_id, page_id)
        return self.retrieve_page(page_id, project_id)

    def unarchive_page(self, page_id: str, project_id: str) -> Page:
        self.client.pages.unarchive_project_page(self.workspace_slug, project_id, page_id)
        return self.retrieve_page(page_id, project_id)

    def delete_page(self, page_id: str, project_id: str) -> None:
        self.client.pages.delete_project_page(self.workspace_slug, project_id, page_id)


class CEPageBackend:
    """Verified project-page operations on CE's session app API."""

    def __init__(self, workspace_slug: str):
        self.workspace_slug = workspace_slug

    def _base(self, project_id: str) -> str:
        return f"workspaces/{self.workspace_slug}/projects/{project_id}/pages/"

    @staticmethod
    def _project_only(project_id: str | None) -> str:
        if project_id is None:
            raise ValueError("Workspace-level pages are not available on Plane Community Edition; pass project_id.")
        return project_id

    def list_pages(self, project_id: str | None, params: dict[str, Any] | None) -> list[Page]:
        project_id = self._project_only(project_id)
        data = get_app_session().get(self._base(project_id), params=params)
        return [Page.model_validate(page) for page in (data or [])]

    def retrieve_page(self, page_id: str, project_id: str | None) -> Page:
        project_id = self._project_only(project_id)
        return Page.model_validate(get_app_session().get(f"{self._base(project_id)}{page_id}/"))

    def create_page(self, data: CreatePage, project_id: str | None) -> Page:
        project_id = self._project_only(project_id)
        # CE has a separate content route; only metadata verified by the probe is
        # sent on create. The v1.4.1 probe showed both hierarchy fields are
        # silently ignored, so reject them before any write.
        capabilities = ce_capabilities()
        if data.parent_id is not None and PAGES_PARENT_ID not in capabilities:
            raise ValueError("Nested pages are not verified on this Plane Community Edition target.")
        if data.collection_id is not None and PAGES_COLLECTION_ID not in capabilities:
            raise ValueError("Page collections are not verified on this Plane Community Edition target.")
        body = {
            key: value
            for key, value in {
                "access": data.access,
                "color": data.color,
                "is_locked": data.is_locked,
                "view_props": data.view_props,
                "logo_props": data.logo_props,
            }.items()
            if value is not None
        }
        body["name"] = data.name
        if data.parent_id is not None:
            body["parent_id"] = data.parent_id
        if data.collection_id is not None:
            body["collection_id"] = data.collection_id
        base = self._base(project_id)
        created = get_app_session().post(base, json=body)
        page_id = created["id"]
        if data.description_html:
            try:
                get_app_session().patch(
                    f"{base}{page_id}/description/", json={"description_html": data.description_html}
                )
            except HttpError as exc:
                raise HttpError(
                    f"Page {page_id} was created but its content update failed; use update_page to retry.",
                    exc.status_code,
                    exc.response,
                ) from exc
        return self.retrieve_page(page_id, project_id)

    def update_page(self, page_id: str, project_id: str, data: UpdatePage) -> Page:
        base = self._base(project_id)
        app = get_app_session()
        if data.name is not None:
            app.patch(f"{base}{page_id}/", json={"name": data.name})
        if data.description_html is not None:
            try:
                app.patch(f"{base}{page_id}/description/", json={"description_html": data.description_html})
            except HttpError as exc:
                if data.name is not None:
                    detail = f"Page {page_id} was only partially updated (name); retry the description_html update."
                else:
                    detail = f"Page {page_id} was not updated; retry the description_html update."
                raise HttpError(detail, exc.status_code, exc.response) from exc
        return self.retrieve_page(page_id, project_id)

    def archive_page(self, page_id: str, project_id: str) -> Page:
        base = self._base(project_id)
        get_app_session().post(f"{base}{page_id}/archive/", json={})
        return self.retrieve_page(page_id, project_id)

    def unarchive_page(self, page_id: str, project_id: str) -> Page:
        base = self._base(project_id)
        get_app_session().delete(f"{base}{page_id}/archive/")
        return self.retrieve_page(page_id, project_id)

    def delete_page(self, page_id: str, project_id: str) -> None:
        get_app_session().delete(f"{self._base(project_id)}{page_id}/")


class OpsPageBackend:
    """Zil Ops project pages over the Ops API (``/api/v1/.../pages/``).

    Content is written as a ``replace_all`` block edit, which Ops applies to the page's
    collaborative document: blocks that did not change keep their identity, and people with the
    page open receive the change like any collaborator's edit. Content may be markdown or HTML.
    """

    def __init__(self, client: PlaneClient, workspace_slug: str):
        self.ops = OpsSession(client, workspace_slug)

    @staticmethod
    def _project_only(project_id: str | None) -> str:
        if not project_id:
            raise ValueError("Zil Ops pages live in projects; pass project_id.")
        return project_id

    @staticmethod
    def _page(data: dict[str, Any]) -> Page:
        data = dict(data)
        data.setdefault("parent_id", data.get("parent"))
        return Page.model_validate(data)

    def list_pages(self, project_id: str | None, params: dict[str, Any] | None) -> list[Page]:
        data = self.ops.page("GET", self._project_only(project_id), params=params or None)
        pages = data.get("results", []) if isinstance(data, dict) else (data or [])
        return [self._page(page) for page in pages]

    def retrieve_page(self, page_id: str, project_id: str | None) -> Page:
        return self._page(self.ops.page("GET", self._project_only(project_id), page_id))

    def _write_content(self, page_id: str, project_id: str, content: str) -> None:
        self.ops.page("POST", project_id, page_id, "edit", json={"ops": [{"op": "replace_all", "content": content}]})

    def create_page(self, data: CreatePage, project_id: str | None) -> Page:
        project_id = self._project_only(project_id)
        if data.collection_id is not None:
            raise ValueError("Zil Ops has no page collections; use parent_id to nest the page.")
        body = {
            key: value
            for key, value in {
                "name": data.name,
                "access": data.access,
                "logo_props": data.logo_props,
                "parent": data.parent_id,
            }.items()
            if value is not None
        }
        page_id = str(self.ops.page("POST", project_id, json=body)["id"])
        if data.description_html:
            try:
                self._write_content(page_id, project_id, data.description_html)
            except HttpError as exc:
                raise HttpError(
                    f"Page {page_id} was created but its content could not be written ({exc}); "
                    "retry with edit_page replace_all.",
                    exc.status_code,
                    exc.response,
                ) from exc
        if data.is_locked:
            self.ops.page("POST", project_id, page_id, "lock")
        return self.retrieve_page(page_id, project_id)

    def update_page(self, page_id: str, project_id: str, data: UpdatePage) -> Page:
        if data.name is not None:
            # Ops applies the name to the document's title too, so open editors show it
            self.ops.page("PATCH", project_id, page_id, json={"name": data.name})
        if data.description_html is not None:
            self._write_content(page_id, project_id, data.description_html)
        return self.retrieve_page(page_id, project_id)

    def archive_page(self, page_id: str, project_id: str) -> Page:
        self.ops.page("POST", project_id, page_id, "archive")
        return self.retrieve_page(page_id, project_id)

    def unarchive_page(self, page_id: str, project_id: str) -> Page:
        self.ops.page("DELETE", project_id, page_id, "archive")
        return self.retrieve_page(page_id, project_id)

    def delete_page(self, page_id: str, project_id: str) -> None:
        raise ValueError("Zil Ops doesn't delete pages through the API; archive the page instead.")


_CE_SESSION_REQUIRED = (
    "Plane Community Edition page operations require app-session credentials; "
    "set PLANE_SESSION_COOKIE or PLANE_SESSION_EMAIL + PLANE_SESSION_PASSWORD."
)


def get_page_backend(client: PlaneClient, workspace_slug: str) -> PageBackend:
    """Resolve the backend for this call; do not cache request-specific state.

    CE without session credentials fails fast here instead of sending a PAT to
    app-API-only routes that would answer a cryptic 401/404.
    """
    if ops_enabled():
        return OpsPageBackend(client, workspace_slug)
    if is_community_edition():
        if not session_auth_available():
            raise ValueError(_CE_SESSION_REQUIRED)
        return CEPageBackend(workspace_slug)
    return CloudPageBackend(client, workspace_slug)
