# Upstream

Vendored from [windyboy/plane-mcp-server-ce](https://github.com/windyboy/plane-mcp-server-ce)
(MIT, see `LICENSE`) at commit `fd5a6539b2f5568993709dce03cc0bbc398d178e` (v0.7.1, 2026-09-21).
Dropped: `.github/`, `scripts/` (session refresh; Ops needs no app session), release/community docs.

## Ops patches

Keep them to these files so an upstream update is a copy plus re-applying this list.

| File                                 | Change                                                                                   |
| ------------------------------------ | ---------------------------------------------------------------------------------------- |
| `plane_mcp/ops.py` (new)             | Ops switch (`OPS_PUBLIC_URL`) and Ops API calls with the caller's token                  |
| `plane_mcp/auth/ops_oauth.py` (new)  | `/mcp` as an OAuth protected resource of Ops; bearer tokens checked against Ops `whoami` |
| `plane_mcp/tools/ops_pages.py` (new) | `search_pages`, `read_page`, `edit_page` (Ops `blocks/` and `edit/` page routes)         |
| `plane_mcp/page_backends.py`         | `OpsPageBackend` (Ops page API), selected when `OPS_PUBLIC_URL` is set                   |
| `plane_mcp/tools/__init__.py`        | register Ops page tools; don't hide `page` on Ops                                        |
| `plane_mcp/server.py`                | `get_ops_mcp()` factory                                                                  |
| `plane_mcp/__main__.py`              | `build_http_app()`: also mounts `/mcp` (OAuth) when Ops is enabled                       |
| `plane_mcp/instructions.py`          | `OPS_INSTRUCTIONS` (how to edit pages)                                                   |
| `plane_mcp/auth/__init__.py`         | exports                                                                                  |
| `tests/test_ops.py` (new)            | tests for all of the above                                                               |

## Updating

1. Copy the new upstream tree over this one (same exclusions), keeping the files above.
2. Re-apply the patches to the modified files (`git diff <this commit>^ -- apps/mcp` shows them).
3. `uv sync --all-extras && uv run ruff check . && uv run pytest`.
