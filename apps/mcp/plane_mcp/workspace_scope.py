"""Zil Ops: which workspace each tool call runs in.

An Ops connection has a main workspace (picked on the consent page). When the person also granted
"all my workspaces", every tool takes an optional ``workspace`` argument (a workspace slug) to run in
another workspace they belong to, and ``list_workspaces`` tells the model which ones exist. The
person's own permissions apply in each workspace; the API enforces them.

The tools themselves don't know about this: ``WorkspaceScopeMiddleware`` adds the argument to the
advertised schemas, takes it out of each call and sets ``current_workspace_override`` for the call,
which ``plane_mcp.client.get_plane_client_context`` honours.
"""

from __future__ import annotations

import contextvars
from collections.abc import Sequence
from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_access_token
from fastmcp.server.middleware import Middleware, MiddlewareContext
from fastmcp.tools import Tool

WORKSPACE_ARG = "workspace"
LIST_WORKSPACES_TOOL = "list_workspaces"

_override: contextvars.ContextVar[str | None] = contextvars.ContextVar("ops_workspace_override", default=None)


def current_workspace_override() -> str | None:
    return _override.get()


def connection_workspaces() -> tuple[str, list[dict[str, str]], bool]:
    """(main workspace slug, workspaces this connection may use, whether it has all of them)."""
    token = get_access_token()
    if token is None:
        return "", [], False
    claims = token.claims or {}
    return claims.get("workspace_slug") or "", list(claims.get("workspaces") or []), bool(claims.get("all_workspaces"))


def _with_workspace_arg(tool: Tool) -> Tool:
    parameters = dict(tool.parameters or {"type": "object", "properties": {}})
    properties = dict(parameters.get("properties") or {})
    if WORKSPACE_ARG in properties:
        return tool
    properties[WORKSPACE_ARG] = {
        "type": "string",
        "description": (
            "Workspace slug to run this in (see list_workspaces). Omit it to use the connection's main workspace."
        ),
    }
    parameters["properties"] = properties
    return tool.model_copy(update={"parameters": parameters})


class WorkspaceScopeMiddleware(Middleware):
    async def on_list_tools(self, context: MiddlewareContext[Any], call_next: Any) -> Sequence[Tool]:
        tools = await call_next(context)
        _, _, all_workspaces = connection_workspaces()
        if not all_workspaces:
            return tools
        return [tool if tool.name == LIST_WORKSPACES_TOOL else _with_workspace_arg(tool) for tool in tools]

    async def on_call_tool(self, context: MiddlewareContext[Any], call_next: Any) -> Any:
        arguments = dict(context.message.arguments or {})
        requested = arguments.pop(WORKSPACE_ARG, None)
        main, workspaces, all_workspaces = connection_workspaces()
        if requested is None or requested == "" or context.message.name == LIST_WORKSPACES_TOOL:
            if not main and all_workspaces and context.message.name != LIST_WORKSPACES_TOOL:
                raise ToolError("This connection has no main workspace: pass `workspace` (see list_workspaces).")
            return await call_next(context)

        allowed = {w["slug"] for w in workspaces} if all_workspaces else {main}
        if requested not in allowed:
            if not all_workspaces:
                raise ToolError(
                    f"This connection only has access to the workspace '{main}'. To use other workspaces, "
                    "reconnect Zil Ops and tick 'Dar acceso también a mis otros espacios' on the consent page."
                )
            raise ToolError(
                f"Unknown workspace '{requested}'. Available: {', '.join(sorted(allowed))} (see list_workspaces)."
            )

        message = context.message.model_copy(update={"arguments": arguments})
        token = _override.set(requested)
        try:
            return await call_next(context.copy(message=message))
        finally:
            _override.reset(token)


def register_workspace_scope(mcp: FastMCP) -> None:
    @mcp.tool(name=LIST_WORKSPACES_TOOL)
    def list_workspaces() -> dict[str, Any]:
        """
        List the Zil Ops workspaces this connection can use.

        The main workspace is used when a tool is called without `workspace`. When the connection has
        access to all the person's workspaces, pass `workspace` (a slug from this list) to any tool to
        run it in another one.
        """
        main, workspaces, all_workspaces = connection_workspaces()
        if not all_workspaces:
            workspaces = [w for w in workspaces if w["slug"] == main] or (
                [{"slug": main, "name": main}] if main else []
            )
        return {
            "main_workspace": main or None,
            "all_workspaces": all_workspaces,
            "workspaces": [{**w, "main": w["slug"] == main} for w in workspaces],
        }

    mcp.add_middleware(WorkspaceScopeMiddleware())
