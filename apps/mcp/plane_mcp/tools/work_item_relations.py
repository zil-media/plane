"""Work item relation tools for Plane MCP Server.

Plane Community Edition exposes its relation API at ``work-items/{id}/relations``.
It supports the eight built-in relation types directly; the older Cloud endpoints
for dependencies and custom relation definitions are not present on CE.
"""

from typing import Any, get_args

from fastmcp import FastMCP
from plane.models.work_items import (
    CreateWorkItemRelation,
    WorkItemRelation,
    WorkItemRelationTypeEnum,
)
from pydantic import BaseModel, ConfigDict, Field, field_validator

from plane_mcp.client import get_plane_client_context

# Relation type values accepted by the CE ``relations/`` endpoint.
_RELATION_TYPES: tuple[str, ...] = get_args(WorkItemRelationTypeEnum)

_RELATION_GROUP_KEYS: tuple[str, ...] = (
    "blocking",
    "blocked_by",
    "duplicate",
    "relates_to",
    "start_after",
    "start_before",
    "finish_after",
    "finish_before",
)


class CEWorkItemRelationRef(BaseModel):
    """One related work item as returned by Plane CE ``relations/`` GET.

    CE returns ``{project_id, issue_id}`` objects. Cloud / older SDK docs describe
    bare UUID strings; both are accepted and normalized here.
    """

    model_config = ConfigDict(extra="allow")

    project_id: str | None = None
    issue_id: str


class CEWorkItemRelationResponse(BaseModel):
    """CE-compatible grouped relations response.

    plane-sdk ``WorkItemRelationResponse`` types each group as ``list[str]``, which
    rejects CE's object payloads and surfaces as MCP ``Invalid request parameters``.
    """

    model_config = ConfigDict(extra="allow")

    blocking: list[CEWorkItemRelationRef] = Field(default_factory=list)
    blocked_by: list[CEWorkItemRelationRef] = Field(default_factory=list)
    duplicate: list[CEWorkItemRelationRef] = Field(default_factory=list)
    relates_to: list[CEWorkItemRelationRef] = Field(default_factory=list)
    start_after: list[CEWorkItemRelationRef] = Field(default_factory=list)
    start_before: list[CEWorkItemRelationRef] = Field(default_factory=list)
    finish_after: list[CEWorkItemRelationRef] = Field(default_factory=list)
    finish_before: list[CEWorkItemRelationRef] = Field(default_factory=list)

    @field_validator(*_RELATION_GROUP_KEYS, mode="before")
    @classmethod
    def _coerce_relation_group(cls, value: Any) -> list[dict[str, Any]]:
        return [_coerce_relation_ref(item) for item in (value or [])]


def _coerce_relation_ref(item: Any) -> dict[str, Any]:
    """Normalize a CE object or Cloud UUID string into ``{project_id?, issue_id}``."""
    if isinstance(item, str):
        return {"issue_id": item}
    if isinstance(item, dict):
        issue_id = item.get("issue_id") or item.get("id")
        if not issue_id:
            raise ValueError(f"relation entry missing issue_id/id: {item!r}")
        out = dict(item)
        out["issue_id"] = str(issue_id)
        return out
    issue_id = getattr(item, "issue_id", None) or getattr(item, "id", None)
    if not issue_id:
        raise ValueError(f"unsupported relation entry: {item!r}")
    project_id = getattr(item, "project_id", None)
    return {"project_id": project_id, "issue_id": str(issue_id)}


def parse_work_item_relations(payload: Any) -> CEWorkItemRelationResponse:
    """Parse a raw ``relations/`` GET body into the CE-compatible response model."""
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump()
    return CEWorkItemRelationResponse.model_validate(payload or {})


def register_work_item_relation_tools(mcp: FastMCP) -> None:
    """Register work item relation tools with the MCP server."""

    @mcp.tool()
    def list_work_item_relations(
        project_id: str,
        work_item_id: str,
    ) -> CEWorkItemRelationResponse:
        """List every relation for a work item.

        Args:
            project_id: UUID of the project.
            work_item_id: UUID of the work item.

        Returns:
            Relations grouped by type (blocking, blocked_by, duplicate,
            relates_to, start_before, start_after, finish_before, finish_after).
            Each entry is ``{project_id, issue_id}`` (CE shape; Cloud UUID strings
            are normalized to the same form).
        """
        client, workspace_slug = get_plane_client_context()
        # Bypass SDK ``WorkItemRelationResponse`` (list[str] groups): CE returns objects.
        raw = client.work_items.relations._get(
            f"{workspace_slug}/projects/{project_id}/work-items/{work_item_id}/relations"
        )
        return parse_work_item_relations(raw)

    @mcp.tool()
    def create_work_item_relation(
        project_id: str,
        work_item_id: str,
        work_item_ids: list[str],
        relation_type: str,
    ) -> list[WorkItemRelation]:
        """Relate a work item to one or more targets.

        Args:
            project_id: UUID of the project.
            work_item_id: UUID of the source work item.
            work_item_ids: UUIDs of the target work items.
            relation_type: One of blocking, blocked_by, duplicate, relates_to,
                start_before, start_after, finish_before, or finish_after.

        Returns:
            Details of the created relations.
        """
        client, workspace_slug = get_plane_client_context()
        if relation_type not in _RELATION_TYPES:
            raise ValueError(f"relation_type must be one of {list(_RELATION_TYPES)}.")
        data = CreateWorkItemRelation(
            relation_type=relation_type,  # type: ignore[arg-type]
            issues=work_item_ids,
        )
        response = client.work_items.relations._post(
            f"{workspace_slug}/projects/{project_id}/work-items/{work_item_id}/relations",
            data.model_dump(exclude_none=True),
        )
        return [WorkItemRelation.model_validate(item) for item in response]

    @mcp.tool()
    def remove_work_item_relation(
        project_id: str,
        work_item_id: str,
        related_work_item_id: str,
    ) -> None:
        """Remove ONE relation between two work items.

        Args:
            project_id: UUID of the project.
            work_item_id: UUID of the source work item.
            related_work_item_id: UUID of the related work item.
        """
        del project_id, work_item_id, related_work_item_id
        raise RuntimeError(
            "Removing work item relations is not available in the tested Plane Community Edition: "
            "it exposes only GET and POST on the relations endpoint."
        )
