# Plane MCP Server CE

MCP server for self-hosted Plane Community Edition.

- Package: `plane-community-mcp`
- Command: `plane-mcp-server-ce`
- Transports: stdio and Streamable HTTP with PAT headers
- OAuth and SSE are not supported.

## Install

Python 3.10 or later is required. Package: `plane-community-mcp`; command:
`plane-mcp-server-ce`.

`uvx` (no install; runs the latest release, or a pinned one):

```bash
uvx --from plane-community-mcp plane-mcp-server-ce --help
uvx --from plane-community-mcp==0.7.1 plane-mcp-server-ce --help
```

`pip` / `pipx`:

```bash
pip install plane-community-mcp
pipx install plane-community-mcp
```

Docker (see [HTTP](#http) for run flags):

```bash
docker build -t plane-mcp-server-ce .
```

Verify an installation:

```bash
plane-mcp-server-ce --help          # pip/pipx
uvx --from plane-community-mcp plane-mcp-server-ce --help   # uvx
```

## Update

How to move an existing setup to a new release.

`uvx` caches the resolved package; pass `--refresh` to pick up the new release:

```bash
uvx --refresh --from plane-community-mcp plane-mcp-server-ce --help
```

MCP client configs using `uvx --from plane-community-mcp …` keep the cache per
client; add `--refresh` once after upgrading, or run the command above
manually, then restart the client. Pinned configs (`==x.y.z`) must be edited
to the new version.

`pip` / `pipx`:

```bash
pip install --upgrade plane-community-mcp
pipx upgrade plane-community-mcp
```

Docker: rebuild the image so the new version is baked in:

```bash
git pull && docker build -t plane-mcp-server-ce .
```

### Upgrading to 0.7.0

- Pages are served by one resource tool, `page(action=...)`, with actions
  `list`, `retrieve`, `create`, `update`, `archive`, `unarchive`, `delete`.
  The previous per-operation tools (`create_page`, `update_page`, …) remain
  callable but no longer appear in `tools/list`; clients that cache tool lists
  should refresh them.
- `update_page` now takes `(page_id, project_id, name=None,
description_html=None)`. MCP calls use named arguments and are unaffected;
  positional callers must switch to named arguments.
- On CE without session credentials, page tools are hidden and direct calls
  fail with a clear credentials error instead of a cryptic 401/404.

## Stdio

Set the Plane URL, API key, and workspace slug:

```bash
export PLANE_BASE_URL="https://plane.example.com"
export PLANE_API_KEY="your-api-key"
export PLANE_WORKSPACE_SLUG="your-workspace"
export PLANE_MCP_EDITION="community"

uvx --from plane-community-mcp plane-mcp-server-ce stdio
```

Example MCP configuration:

```json
{
  "mcpServers": {
    "plane": {
      "command": "uvx",
      "args": ["--from", "plane-community-mcp", "plane-mcp-server-ce", "stdio"],
      "env": {
        "PLANE_BASE_URL": "https://plane.example.com",
        "PLANE_API_KEY": "your-api-key",
        "PLANE_WORKSPACE_SLUG": "your-workspace",
        "PLANE_MCP_EDITION": "community"
      }
    }
  }
}
```

## HTTP

Start the server:

```bash
export PLANE_BASE_URL="https://plane.example.com"
export PLANE_MCP_EDITION="community"
uvx --from plane-community-mcp plane-mcp-server-ce http
```

Endpoint:

```text
http://<host>:8211/http/api-key/mcp
```

Clients must send both headers:

```text
Authorization: Bearer <api-key>
x-workspace-slug: <workspace-slug>
```

Example with `mcp-remote`:

```json
{
  "mcpServers": {
    "plane": {
      "command": "npx",
      "args": [
        "mcp-remote@latest",
        "http://plane-mcp:8211/http/api-key/mcp",
        "--header",
        "Authorization: Bearer ${PLANE_API_KEY}",
        "--header",
        "x-workspace-slug: ${PLANE_WORKSPACE_SLUG}"
      ]
    }
  }
}
```

Docker:

```bash
docker build -t plane-mcp-server-ce .
docker run -p 8211:8211 \
  -e PLANE_BASE_URL="https://plane.example.com" \
  -e PLANE_MCP_EDITION="community" \
  plane-mcp-server-ce
```

## Configuration

| Variable                  | Required                  | Description                                                                                       |
| ------------------------- | ------------------------- | ------------------------------------------------------------------------------------------------- |
| `PLANE_BASE_URL`          | Yes for self-hosted Plane | Plane instance origin.                                                                            |
| `PLANE_API_KEY`           | stdio                     | Personal API key.                                                                                 |
| `PLANE_WORKSPACE_SLUG`    | stdio                     | Workspace slug.                                                                                   |
| `PLANE_MCP_EDITION`       | Recommended               | Set to `community` for CE-only tool discovery.                                                    |
| `PLANE_CE_CAPABILITIES`   | No                        | Comma-separated CE capability keys (e.g. `pages.parent_id`) enabled beyond the verified baseline. |
| `PLANE_INTERNAL_BASE_URL` | No                        | Internal Plane URL for server-to-server calls.                                                    |
| `MCP_PATH_PREFIX`         | No                        | HTTP route prefix.                                                                                |
| `LOG_LEVEL`               | No                        | Python log level; default `INFO`.                                                                 |
| `LOG_USER_INFO`           | No                        | Set to `true` to include display name in logs.                                                    |

### Session-only CE tools

CE exposes project pages and work-item archive operations through its app API,
not the public API. Enable these tools with either a session cookie or login
credentials:

```bash
export PLANE_SESSION_COOKIE="<session-id-cookie>"
# Or:
export PLANE_SESSION_EMAIL="you@example.com"
export PLANE_SESSION_PASSWORD="your-password"
```

Without these variables, session-only tools are hidden. Prefer a session cookie
over an account password. The cookie is the `session-id` value from an active
browser session and must be replaced when it expires.

A cookie cannot be renewed in-process: once it expires, a 401 retry only
re-fetches the CSRF token, so the server cannot recover until it is restarted
with a fresh value. Refresh it out of band with `scripts/refresh-session.sh`,
which signs in with `PLANE_SESSION_EMAIL` / `PLANE_SESSION_PASSWORD` (no
browser needed) and rewrites `PLANE_SESSION_COOKIE` in your env file
(atomically, keeping its permissions; the cookie value is never echoed):

```bash
./scripts/refresh-session.sh                     # default env file: ~/.config/plane-mcp/env
./scripts/refresh-session.sh /path/to/env-file   # or pass one explicitly
```

Requires `curl` and `python3`. Restart the MCP server afterwards — the cookie
is only read at process start. Run it manually or from cron before the
session expires.

Page operations are exposed through the `page(action=...)` resource tool
(`list`, `retrieve`, `create`, `update`, `archive`, `unarchive`, `delete`).
The previous per-operation names below remain callable but are hidden from
discovery, so existing clients keep working. `update_page` /
`page(action="update")` accepts `name` and/or `description_html`; on CE they
are applied through the app API's separate name and content routes, in that
order. On Plane Cloud all page actions use the public SDK/API path.

| Old tool              | Replacement                                 |
| --------------------- | ------------------------------------------- |
| `list_pages`          | `page(action="list")`                       |
| `retrieve_page`       | `page(action="retrieve")`                   |
| `create_page`         | `page(action="create")`                     |
| `update_page`         | `page(action="update")`                     |
| `update_page_content` | `page(action="update", description_html=…)` |
| `archive_page`        | `page(action="archive")`                    |
| `unarchive_page`      | `page(action="unarchive")`                  |
| `delete_page`         | `page(action="delete")`                     |

On CE, `parent_id`/`collection_id` on `page(action="create")` are rejected
before any write (silently ignored on every target probed so far). Set
`PLANE_CE_CAPABILITIES` (comma-separated, e.g. `pages.parent_id`) to enable
them on a target you have verified yourself; see
[CE_COMPAT.md](CE_COMPAT.md).

## CE scope

CE mode exposes supported projects, work items, cycles, modules, labels,
states, comments, links, attachments, activities, and project pages. Unsupported
or partial endpoints are omitted from discovery where possible. See
[CE_COMPAT.md](CE_COMPAT.md) for endpoint evidence and the complete matrix.

## Logging

Logs are JSON. Each tool call emits one success or error event with the tool
name and duration. Request payloads are not logged.

## Development

```bash
uv sync --all-extras
uv run ruff check .
uv run pytest
```

## Release

See [RELEASING.md](RELEASING.md).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE)
