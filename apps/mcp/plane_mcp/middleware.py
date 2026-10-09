"""Custom FastMCP middleware for the Plane MCP Server."""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from typing import Any

from fastmcp.server.middleware import Middleware, MiddlewareContext
from fastmcp.server.middleware.logging import StructuredLoggingMiddleware
from fastmcp.tools import Tool


class PlaneToolVisibilityMiddleware(Middleware):
    """Keep compatibility-alias tools callable but out of MCP discovery.

    ``tools/list`` responses drop the hidden names; ``tools/call`` is untouched,
    so existing clients keep working while new clients see only the canonical
    resource tools. See PAGE_ALIAS_TOOLS in ``plane_mcp.tools``.
    """

    def __init__(self, hidden_tools: frozenset[str]) -> None:
        self.hidden_tools = frozenset(hidden_tools)

    async def on_list_tools(
        self,
        context: MiddlewareContext[Any],
        call_next: Any,
    ) -> Sequence[Tool]:
        tools = await call_next(context)
        return [tool for tool in tools if tool.name not in self.hidden_tools]


class PlaneLoggingMiddleware(StructuredLoggingMiddleware):
    """Emit one structured event for each tool invocation.

    Protocol traffic such as initialize, ping, and tools/list is intentionally
    excluded. Tool arguments can be enabled explicitly for short-lived
    debugging, but are not safe or useful enough to log by default.
    """

    def __init__(self, *, include_payloads: bool = False) -> None:
        super().__init__(
            include_payloads=include_payloads,
            methods=["tools/call"],
        )

    def _with_tool_name(self, context: MiddlewareContext[Any], message: dict) -> dict:
        params = getattr(context.message, "params", context.message)
        message["tool"] = getattr(params, "name", "unknown")
        return message

    def _create_after_message(self, context: MiddlewareContext[Any], start_time: float) -> dict:
        message = super()._create_after_message(context, start_time)
        message["event"] = "tool_success"
        return self._with_tool_name(context, message)

    def _create_error_message(self, context: MiddlewareContext[Any], start_time: float, error: Exception) -> dict:
        message = super()._create_error_message(context, start_time, error)
        message["event"] = "tool_error"
        return self._with_tool_name(context, message)

    async def on_message(self, context: MiddlewareContext[Any], call_next: Any) -> Any:
        """Log completion or failure, rather than both start and completion."""
        if context.method != "tools/call":
            return await call_next(context)

        start_time = time.perf_counter()
        try:
            result = await call_next(context)
        except Exception as error:
            self._log_message(self._create_error_message(context, start_time, error), logging.ERROR)
            raise

        self._log_message(self._create_after_message(context, start_time))
        return result
