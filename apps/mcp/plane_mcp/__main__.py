"""Main entry point for the Plane MCP Server."""

import contextlib
import json
import logging
import os
import sys
from datetime import datetime, timezone
from enum import Enum

import uvicorn
from fastmcp.server.dependencies import get_access_token
from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.routing import Mount

from plane_mcp.ops import ops_enabled
from plane_mcp.server import get_header_mcp, get_ops_mcp, get_stdio_mcp

LOG_USER_INFO: bool = os.getenv("LOG_USER_INFO", "").lower() == "true"
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()


class UserContextFilter(logging.Filter):
    """Attach authenticated user/workspace context to every log record.

    Pulls the current request's access token via FastMCP's dependency, which
    returns None (never raises) outside a request context — so startup logs fall
    back to environment config and otherwise carry no user info.

    Always logs the opaque user id (sub claim) and the workspace slug; neither is
    PII. The display name IS PII and is only included when LOG_USER_INFO=true.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        user_id = None
        display_name = None
        workspace_slug = None
        try:
            token = get_access_token()
            if token:
                user_id = token.claims.get("sub")
                workspace_slug = token.claims.get("workspace_slug")
                if LOG_USER_INFO:
                    display_name = token.claims.get("display_name")
        except Exception as exc:
            # Never let logging enrichment break a request, but leave a signal.
            record.user_context_enrichment_error = type(exc).__name__
        record.user_id = user_id
        record.display_name = display_name
        # stdio mode has no token; fall back to the configured workspace.
        record.workspace_slug = workspace_slug or os.getenv("PLANE_WORKSPACE_SLUG") or None
        return True


class JSONFormatter(logging.Formatter):
    """JSON log formatter for structured logging (Datadog, ELK, etc.)."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
        }
        # The logging middleware emits a JSON object as its log message. Promote
        # those keys to top-level fields (event, method, tool, duration_ms, ...)
        raw_message = record.getMessage()
        try:
            parsed = json.loads(raw_message)
        except (ValueError, TypeError):
            parsed = None
        if isinstance(parsed, dict):
            log_entry.update(parsed)
        else:
            log_entry["message"] = raw_message
        user_id = getattr(record, "user_id", None)
        if user_id:
            log_entry["user_id"] = user_id
        workspace_slug = getattr(record, "workspace_slug", None)
        if workspace_slug:
            log_entry["workspace_slug"] = workspace_slug
        display_name = getattr(record, "display_name", None)
        if display_name:
            log_entry["display_name"] = display_name
        err = getattr(record, "user_context_enrichment_error", None)
        if err:
            log_entry["user_context_enrichment_error"] = err
        if record.exc_info and record.exc_info[1]:
            log_entry["error"] = str(record.exc_info[1])
            log_entry["error_type"] = type(record.exc_info[1]).__name__
        return json.dumps(log_entry)


def configure_json_logging():
    """Replace FastMCP's Rich handlers with a JSON formatter on the fastmcp logger."""
    fastmcp_logger = logging.getLogger("fastmcp")

    # Remove all existing handlers (Rich)
    for handler in fastmcp_logger.handlers[:]:
        fastmcp_logger.removeHandler(handler)

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JSONFormatter())
    handler.addFilter(UserContextFilter())
    fastmcp_logger.addHandler(handler)
    fastmcp_logger.setLevel(LOG_LEVEL)
    fastmcp_logger.propagate = False


configure_json_logging()

logger = logging.getLogger("fastmcp.plane_mcp")


def build_http_app() -> Starlette:
    """The HTTP ASGI app: the PAT-header endpoint, plus Zil Ops' OAuth endpoint at /mcp."""
    prefix = os.getenv("MCP_PATH_PREFIX") or ""

    header_app = get_header_mcp().http_app(stateless_http=True)
    # PAT (header) endpoint: clients authenticate with x-api-key + x-workspace-slug headers.
    routes = [Mount(prefix + "/http/api-key", app=header_app)]
    sub_apps = [header_app]
    if ops_enabled():
        # Zil Ops: OAuth-protected /mcp; its protected-resource metadata routes come with it
        ops_app = get_ops_mcp().http_app(path="/mcp", stateless_http=True)
        routes.append(Mount("/", app=ops_app))
        sub_apps.append(ops_app)

    @contextlib.asynccontextmanager
    async def lifespan(_app):
        async with contextlib.AsyncExitStack() as stack:
            for sub_app in sub_apps:
                await stack.enter_async_context(sub_app.lifespan(sub_app))
            yield

    app = Starlette(routes=routes, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["WWW-Authenticate", "Mcp-Session-Id"],
    )
    return app


class ServerMode(Enum):
    STDIO = "stdio"
    HTTP = "http"


def main() -> None:
    """Run the MCP server."""
    if len(sys.argv) > 1 and sys.argv[1] in {"-h", "--help"}:
        print("Usage: plane-mcp-server-ce [stdio|http]")
        return

    server_mode = ServerMode.STDIO
    if len(sys.argv) > 1:
        server_mode = ServerMode(sys.argv[1])

    if server_mode == ServerMode.STDIO:
        # Validate API_KEY and PLANE_WORKSPACE_SLUG are set
        if not os.getenv("PLANE_API_KEY"):
            raise ValueError("PLANE_API_KEY is not set")
        if not os.getenv("PLANE_WORKSPACE_SLUG"):
            raise ValueError("PLANE_WORKSPACE_SLUG is not set")

        get_stdio_mcp().run()
        return

    if server_mode == ServerMode.HTTP:
        app = build_http_app()

        # Configure uvicorn loggers to use JSON formatting too
        for uv_logger_name in ("uvicorn", "uvicorn.error"):
            uv_logger = logging.getLogger(uv_logger_name)
            for h in uv_logger.handlers[:]:
                uv_logger.removeHandler(h)
            uv_handler = logging.StreamHandler(sys.stderr)
            uv_handler.setFormatter(JSONFormatter())
            uv_handler.addFilter(UserContextFilter())
            uv_logger.addHandler(uv_handler)
            uv_logger.setLevel(LOG_LEVEL)

        logger.info(
            "Starting HTTP server: MCP endpoint at /http/api-key/mcp (PAT headers)%s",
            " and /mcp (Zil Ops OAuth)" if ops_enabled() else "",
        )
        uvicorn.run(
            app,
            host="0.0.0.0",
            port=8211,
            log_level="info",
            access_log=False,
        )
        return


if __name__ == "__main__":
    main()
