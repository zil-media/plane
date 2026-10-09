# Ops MCP

Remote MCP server for Zil Ops at **`https://ops.zil.global/mcp`**. Nothing to install: the person
adds the URL as a connector and signs in to Ops.

## Connect

- **Claude (web / desktop):** Settings → Connectors → Add custom connector → URL
  `https://ops.zil.global/mcp` → Connect → sign in to Ops → **Permitir**.
- **Claude Code:** `claude mcp add --transport http zil-ops https://ops.zil.global/mcp`, then
  `/mcp` → zil-ops → Authenticate.

Everything runs as the person who connected, with their Ops permissions. The connection shows up
as a personal access token (`<app> (conector)`) under Settings → Profile → Personal access
tokens; deleting it disconnects the app. Tokens last 24h and the app renews them on its own.

## What it can do

Work items, cycles, modules, labels, states, members, comments, links, attachments, intake (the
CE-verified tool set of the vendored server), plus pages:

- `search_pages`: find pages by title or content.
- `read_page`: the page as markdown with a block ref per line.
- `edit_page`: precise edits (replace a phrase, rewrite/insert/delete/move a block, toggle a task,
  replace all). Edits apply to the collaborative document, so they merge with people editing the
  page at the same time and only the touched blocks change.
- `page`: create, rename, archive, restore (no deletes through the API).

## How it is built

| Piece                                                                                                      | Where                                                                                 |
| ---------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| MCP server (vendored [plane-mcp-server-ce](https://github.com/windyboy/plane-mcp-server-ce) + Ops patches) | `apps/mcp` (see `apps/mcp/UPSTREAM.md`)                                               |
| OAuth authorization server, consent page                                                                   | `apps/api/plane/mcp_oauth`                                                            |
| Page API (`/api/v1/.../pages/`, incl. `blocks/` and `edit/`)                                               | `apps/api/plane/api/views/page.py`                                                    |
| Page search, whoami                                                                                        | `apps/api/plane/api/views/zil_mcp.py`                                                 |
| Block-level read/edit on the Yjs doc (called by the API)                                                   | `apps/live/src/lib/page-edit`, `apps/live/src/controllers/page-content.controller.ts` |
| Routing                                                                                                    | `apps/proxy/Caddyfile.ce` (`/mcp`, `/.well-known/...`)                                |

## Deploy (self-host)

Image `ghcr.io/zil-media/plane-mcp` is built by `build-and-push.yml`. The host compose needs an
`mcp` service next to `api` and `live`:

```yaml
mcp:
  image: ghcr.io/zil-media/plane-mcp:preview
  restart: always
  environment:
    PLANE_MCP_EDITION: community
    PLANE_INTERNAL_BASE_URL: http://api:8000
    OPS_PUBLIC_URL: https://ops.zil.global
  depends_on: [api]
```

`APP_BASE_URL` (or `WEB_URL`) on `api` must be the public origin (`https://ops.zil.global`): it is
the OAuth issuer and must match `OPS_PUBLIC_URL`. Block edits use the same api → live link as the
page API (`LIVE_BASE_URL` + `LIVE_SERVER_SECRET_KEY` on `api`).
