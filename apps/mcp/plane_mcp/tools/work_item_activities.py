"""Work item activity-related tools for Plane MCP Server."""

from typing import Any

from fastmcp import FastMCP
from plane.models.work_items import (
    WorkItemActivity,
)
from pydantic import Field

from plane_mcp.client import get_plane_client_context


class CEWorkItemActivity(WorkItemActivity):
    """Activity response as returned by Plane Community Edition.

    CE returns a sub-second Unix timestamp for ``epoch`` while plane-sdk 0.2.19
    types it as an integer.  Keep the fractional precision instead of rejecting
    an otherwise valid API response.
    """

    epoch: float | None = Field(default=None)


def register_work_item_activity_tools(mcp: FastMCP) -> None:
    """Register all work item activity-related tools with the MCP server."""

    @mcp.tool()
    def list_work_item_activities(
        project_id: str,
        work_item_id: str,
        params: dict[str, Any] | None = None,
    ) -> list[CEWorkItemActivity]:
        """
        List activities for a work item.

        Args:
            project_id: UUID of the project
            work_item_id: UUID of the work item
            params: Optional query parameters as a dictionary

        Returns:
            List of WorkItemActivity objects
        """
        client, workspace_slug = get_plane_client_context()
        response = client.work_items.activities._get(
            f"{workspace_slug}/projects/{project_id}/work-items/{work_item_id}/activities",
            params=params,
        )
        return [CEWorkItemActivity.model_validate(item) for item in response.get("results", [])]

    @mcp.tool()
    def retrieve_work_item_activity(
        project_id: str,
        work_item_id: str,
        activity_id: str,
    ) -> CEWorkItemActivity:
        """
        Retrieve a specific activity for a work item.

        Args:
            project_id: UUID of the project
            work_item_id: UUID of the work item
            activity_id: UUID of the activity

        Returns:
            WorkItemActivity object
        """
        client, workspace_slug = get_plane_client_context()
        response = client.work_items.activities._get(
            f"{workspace_slug}/projects/{project_id}/work-items/{work_item_id}/activities/{activity_id}"
        )
        return CEWorkItemActivity.model_validate(response)
