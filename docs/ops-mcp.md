# Ops MCP

Remote MCP server for Zil Ops at **`https://ops.zil.global/mcp`**. Nothing to install: the person
adds the URL as a connector and signs in to Ops.

## Connect

Every person sees the URL and these steps in Ops under **Settings → Profile → Conectar con Claude**
(`apps/web/core/components/settings/profile/content/pages/connect-claude.tsx`).

- **Claude (web / desktop):** Settings → Connectors → Add custom connector → URL
  `https://ops.zil.global/mcp` → Connect → sign in to Ops → **Permitir**.
- **Claude Code:** `claude mcp add --transport http zil-ops https://ops.zil.global/mcp`, then
  `/mcp` → zil-ops → Authenticate.

Everything runs as the person who connected, with their Ops permissions.

On the consent page the person picks a **main workspace** and can tick _Dar acceso también a mis
otros espacios_. Without it the connection only works in the main workspace. With it,
`list_workspaces` lists every workspace the person belongs to and every tool takes an optional
`workspace` (slug) to run there; without the argument tools use the main one
(`apps/mcp/plane_mcp/workspace_scope.py`). Reconnecting the same app replaces the previous
connection, so changing this means connecting again. The API enforces the same limit: a
single-workspace connection gets a 403 on any other workspace's routes
(`apps/api/plane/api/middleware/api_authentication.py`). The connection shows up
as a personal access token (`<app> (conector)`) under Settings → Profile → Personal access
tokens; deleting it disconnects the app. Tokens last 24h and the app renews them on its own.

## What it can do

Work items, cycles, modules, labels, states, members, comments, links, attachments, intake (the
CE-verified tool set of the vendored server), plus pages. Features Plane CE lacks (custom
properties, PQL filters) are hidden or refused with a clear error, and member lists are filtered
and paged by the MCP because the CE endpoints take no query parameters.

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

Attachments: the MCP calls the API with the public host, so presigned URLs are signed for it, and
sends the upload/download straight to the object store (`OPS_STORAGE_INTERNAL_URL`, default
`http://plane-minio:9000`) instead of out through the CDN, which blocks server clients.

`APP_BASE_URL` (or `WEB_URL`) on `api` must be the public origin (`https://ops.zil.global`): it is
the OAuth issuer and must match `OPS_PUBLIC_URL`. Block edits use the same api → live link as the
page API (`LIVE_BASE_URL` + `LIVE_SERVER_SECRET_KEY` on `api`).
