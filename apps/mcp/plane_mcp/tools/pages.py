"""Page-related tools for Plane MCP Server."""

from typing import Any

from fastmcp import FastMCP
from plane.models.pages import CreatePage, Page, UpdatePage
from plane.models.work_item_pages import CreateWorkItemPage, WorkItemPage

from plane_mcp.client import get_plane_client_context
from plane_mcp.page_backends import get_page_backend

# Community Edition serves pages only on the app API, in *project* scope. Workspace
# pages and work-item<->page links do not exist on CE at all; the CE backend
# rejects workspace-scope calls in pre-flight (see CE_COMPAT.md).

# -- resource tool (official-style ``page(action=...)``) ----------------------
#
# One tool per resource, mirroring the official Plane MCP surface. The
# per-operation tool names above stay callable as compatibility aliases but are
# hidden from discovery (see PAGE_ALIAS_TOOLS in plane_mcp.tools).

_PAGE_ACTION_REQUIRED: dict[str, frozenset[str]] = {
    "list": frozenset(),
    "retrieve": frozenset({"page_id"}),
    "create": frozenset({"name"}),
    "update": frozenset({"page_id", "project_id"}),
    "archive": frozenset({"page_id", "project_id"}),
    "unarchive": frozenset({"page_id", "project_id"}),
    "delete": frozenset({"page_id", "project_id"}),
}


def _validate_page_action(action: str, provided: dict[str, Any]) -> None:
    """Reject unknown actions and missing required arguments before any request."""
    if action not in _PAGE_ACTION_REQUIRED:
        raise ValueError(f"Unknown page action {action!r}; choose one of: {', '.join(sorted(_PAGE_ACTION_REQUIRED))}.")
    missing = _PAGE_ACTION_REQUIRED[action] - {key for key, value in provided.items() if value is not None}
    if missing:
        raise ValueError(f"page action {action!r} requires {', '.join(sorted(missing))}.")
    if action == "update" and provided.get("name") is None and provided.get("description_html") is None:
        raise ValueError("page action 'update' requires name and/or description_html.")


def register_page_tools(mcp: FastMCP) -> None:
    """Register all page-related tools with the MCP server."""

    @mcp.tool()
    def list_pages(
        project_id: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> list[Page]:
        """
        List pages.

        Lists a project's pages if project_id is given, otherwise workspace-level pages.

        Args:
            project_id: UUID of the project. Omit to list workspace pages.
            params: Optional query parameters as a dictionary (e.g., per_page, cursor)

        Returns:
            List of Page objects
        """
        client, workspace_slug = get_plane_client_context()

        return get_page_backend(client, workspace_slug).list_pages(project_id, params)

    @mcp.tool()
    def attach_page_to_work_item(
        project_id: str,
        work_item_id: str,
        page_id: str,
    ) -> WorkItemPage:
        """
        Link a page to a work item.

        Args:
            project_id: UUID of the project
            work_item_id: UUID of the work item
            page_id: UUID of the page to link

        Returns:
            WorkItemPage link object
        """
        client, workspace_slug = get_plane_client_context()
        return client.work_items.pages.create(
            workspace_slug=workspace_slug,
            project_id=project_id,
            work_item_id=work_item_id,
            data=CreateWorkItemPage(page_id=page_id),
        )

    @mcp.tool()
    def list_work_item_pages(
        project_id: str,
        work_item_id: str,
    ) -> list[WorkItemPage]:
        """
        List all pages linked to a work item.

        Args:
            project_id: UUID of the project
            work_item_id: UUID of the work item

        Returns:
            List of WorkItemPage link objects
        """
        client, workspace_slug = get_plane_client_context()
        response = client.work_items.pages.list(
            workspace_slug=workspace_slug,
            project_id=project_id,
            work_item_id=work_item_id,
        )
        return response.results

    @mcp.tool()
    def detach_page_from_work_item(
        project_id: str,
        work_item_id: str,
        work_item_page_id: str,
    ) -> None:
        """
        Remove a page link from a work item.

        Args:
            project_id: UUID of the project
            work_item_id: UUID of the work item
            work_item_page_id: UUID of the work item page link (not the page ID)
        """
        client, workspace_slug = get_plane_client_context()
        client.work_items.pages.delete(
            workspace_slug=workspace_slug,
            project_id=project_id,
            work_item_id=work_item_id,
            work_item_page_id=work_item_page_id,
        )

    @mcp.tool()
    def retrieve_page(
        page_id: str,
        project_id: str | None = None,
    ) -> Page:
        """
        Retrieve a page by ID.

        Retrieves a project page if project_id is given, otherwise a workspace page.

        Args:
            page_id: UUID of the page
            project_id: UUID of the project. Omit for a workspace page.

        Returns:
            Page object
        """
        client, workspace_slug = get_plane_client_context()

        return get_page_backend(client, workspace_slug).retrieve_page(page_id, project_id)

    @mcp.tool()
    def create_page(
        name: str,
        description_html: str,
        project_id: str | None = None,
        access: int | None = None,
        color: str | None = None,
        is_locked: bool | None = None,
        archived_at: str | None = None,
        view_props: dict[str, Any] | None = None,
        logo_props: dict[str, Any] | None = None,
        external_id: str | None = None,
        external_source: str | None = None,
        parent_id: str | None = None,
        collection_id: str | None = None,
    ) -> Page:
        """
        Create a page.

        Creates a project page if project_id is given, otherwise a
        workspace-level page.

        Args:
            name: Page name
            description_html: Page content in HTML format
            project_id: UUID of the project. Omit to create a workspace page.
            access: Access level for the page (integer)
            color: Page color
            is_locked: Whether the page is locked
            archived_at: Archive timestamp (ISO 8601 format)
            view_props: View properties dictionary
            logo_props: Logo properties dictionary
            external_id: External system identifier
            external_source: External system source name
            parent_id: Parent page UUID. Cloud only until a CE target supports it.
            collection_id: Collection UUID. Cloud only until a CE target supports it.

        Returns:
            Created Page object
        """
        data = CreatePage(
            name=name,
            description_html=description_html,
            access=access,
            color=color,
            is_locked=is_locked,
            archived_at=archived_at,
            view_props=view_props,
            logo_props=logo_props,
            external_id=external_id,
            external_source=external_source,
            parent_id=parent_id,
            collection_id=collection_id,
        )

        client, workspace_slug = get_plane_client_context()
        return get_page_backend(client, workspace_slug).create_page(data, project_id)

    @mcp.tool()
    def update_page(
        page_id: str,
        project_id: str,
        name: str | None = None,
        description_html: str | None = None,
    ) -> Page:
        """Update a project page's name and/or HTML content.

        At least one field is required. Cloud performs one SDK update; CE applies
        name and content through its verified app routes, in that order.
        """
        if name is None and description_html is None:
            raise ValueError("Pass name and/or description_html when updating a page.")
        client, workspace_slug = get_plane_client_context()
        return get_page_backend(client, workspace_slug).update_page(
            page_id, project_id, UpdatePage(name=name, description_html=description_html)
        )

    @mcp.tool()
    def update_page_content(
        page_id: str,
        description_html: str,
        project_id: str,
    ) -> Page:
        """Compatibility entry point for updating a page's HTML content."""
        return update_page(page_id, project_id, description_html=description_html)

    @mcp.tool()
    def archive_page(page_id: str, project_id: str) -> Page:
        """Archive a project page through the SDK or CE app-session backend."""
        client, workspace_slug = get_plane_client_context()
        return get_page_backend(client, workspace_slug).archive_page(page_id, project_id)

    @mcp.tool()
    def unarchive_page(page_id: str, project_id: str) -> Page:
        """Unarchive a project page through the SDK or CE app-session backend."""
        client, workspace_slug = get_plane_client_context()
        return get_page_backend(client, workspace_slug).unarchive_page(page_id, project_id)

    @mcp.tool()
    def delete_page(page_id: str, project_id: str) -> None:
        """Delete an archived project page.

        Both Cloud and CE reject deleting an active page; call ``archive_page``
        and read it back before deleting.
        """
        client, workspace_slug = get_plane_client_context()
        get_page_backend(client, workspace_slug).delete_page(page_id, project_id)

    @mcp.tool()
    def page(
        action: str,
        page_id: str | None = None,
        project_id: str | None = None,
        name: str | None = None,
        description_html: str | None = None,
        parent_id: str | None = None,
        collection_id: str | None = None,
        params: dict[str, Any] | None = None,
        access: int | None = None,
        color: str | None = None,
        is_locked: bool | None = None,
        view_props: dict[str, Any] | None = None,
        logo_props: dict[str, Any] | None = None,
        external_id: str | None = None,
        external_source: str | None = None,
    ) -> Any:
        """Operate on Plane pages through one resource tool, selected by ``action``.

        Actions and their required arguments (validated before any request):
        - ``list``: list project pages (``project_id``) or workspace pages (omit); optional ``params``
        - ``retrieve``: fetch one page (``page_id``; ``project_id`` optional)
        - ``create``: create a page (``name``; ``project_id`` optional)
        - ``update``: change name and/or content (``page_id``, ``project_id``,
          plus at least one of ``name``/``description_html``)
        - ``archive`` / ``unarchive``: toggle archived state (``page_id``, ``project_id``)
        - ``delete``: delete an archived page (``page_id``, ``project_id``)

        Omitting ``project_id`` targets workspace pages, a Plane Cloud capability:
        on Community Edition every page action requires ``project_id`` and
        workspace-scope calls are rejected before any request.

        ``parent_id``/``collection_id`` (create only) are Cloud capabilities; on CE
        they are rejected before any write unless verified for the target.

        Returns:
            Page, list of Page objects, or None for delete
        """
        _validate_page_action(
            action,
            {
                "page_id": page_id,
                "project_id": project_id,
                "name": name,
                "description_html": description_html,
            },
        )
        client, workspace_slug = get_plane_client_context()
        backend = get_page_backend(client, workspace_slug)
        if action == "list":
            return backend.list_pages(project_id, params)
        if action == "retrieve":
            return backend.retrieve_page(page_id, project_id)
        if action == "create":
            return backend.create_page(
                CreatePage(
                    name=name,
                    description_html=description_html or "",
                    access=access,
                    color=color,
                    is_locked=is_locked,
                    view_props=view_props,
                    logo_props=logo_props,
                    external_id=external_id,
                    external_source=external_source,
                    parent_id=parent_id,
                    collection_id=collection_id,
                ),
                project_id,
            )
        if action == "update":
            return backend.update_page(page_id, project_id, UpdatePage(name=name, description_html=description_html))
        if action == "archive":
            return backend.archive_page(page_id, project_id)
        if action == "unarchive":
            return backend.unarchive_page(page_id, project_id)
        return backend.delete_page(page_id, project_id)
