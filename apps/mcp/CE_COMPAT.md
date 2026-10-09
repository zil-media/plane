# CE_COMPAT.md — MCP and Plane Community Edition Compatibility

> Tracking document for each MCP tool tested against a self-hosted **Plane CE**
> instance. The goal is that every capability available in CE is usable through
> MCP. Cloud-only capabilities are outside this project's scope, but must fail
> clearly rather than with a cryptic 404.
>
> Evidence comes from the in-memory stdio harness in
> `tests/harness_probe.py` and inspection of real CE routes in
> `plane/api/urls/*.py`. Last full run: **2026-07-17**, CE `stable`, workspace
> `optimis-test`, project `OPTIM`.

## Primary Compatibility Causes

The official `plane-sdk` targets Cloud endpoints that CE does not register under
`/api/v1`. There are three major categories:

1. **`*-lite` endpoints** (`projects-lite`, `project-members-lite`,
   `members-lite`, lite cycles, and lite modules) return **404** in CE. Their
   full endpoints return the equivalent data.
2. **Path variants**: CE exposes `work-items/{id}/relations/`, whereas the SDK
   previously used the older `issues/{id}/issue-relation/` path.
3. **SDK Pydantic model mismatches**: an endpoint can return 200 while parsing
   fails (`epoch` integer versus float, UUID assignees versus `UserLite`, or a
   string versus integer `sequence_id`).

## Verified CE Routes

CE registers these under `/api/v1/`: `projects/`, `projects/{id}/`,
`.../members/`, `.../project-members/`, `.../summary/`, `.../estimates/`,
`.../cycles/` (including archive, cycle-issues, transfer-issues, and archived
cycles), `.../modules/` (including module-issues, archive, and archived
modules), `.../labels/`, `.../states/`, `.../intake-issues/`, and both
`.../issues/` and `.../work-items/`. Work-item sub-resources include
`activities/`, `comments/`, `links/`, `issue-attachments/` (also
`attachments/`), and `relations/` only below `work-items/`. Workspace routes
include `members/`, `issues/search/` (also `work-items/search/`), and
`issues/{project}-{sequence}`. User route: `users/me/`.

This CE does **not** register the following under `/api/v1/` (they return 404):
`features`, `roles`, `initiatives`, `milestones`, work-item relation
definitions, `count`, work logs and total-worklogs, archived work items, pages,
issue types/work-item types, and work-item property values.

---

## Results Matrix (run 2026-07-17)

### ✅ Works unchanged (15)

`get_me`, `get_pql_reference`, `search_work_items`, `retrieve_project`,
`list_labels`, `retrieve_label`, `list_states`, `retrieve_state`,
`list_work_items`\*_, `retrieve_work_item`_, `list_intake_work_items`,
`list_work_item_properties`†, `list_work_item_comments`,
`list_work_item_links`, and `list_work_item_attachments`.

> \* `retrieve_work_item` works only when the item has no assignee or label;
> otherwise model validation fails. See BUG-2.
>
> † `list_work_item_properties` returned success but should be retested; CE has
> no apparent property route and may be returning an empty response silently.
>
> \*\* CE accepts list, pagination, and ordering, but silently ignores `pql`.
> CE discovery therefore omits that parameter, unlike Cloud mode.

### 🔧 Category 1 — Correctable endpoint variants

| MCP tool                   | SDK request                                 | CE route (200)               | Fix                                                                    |
| -------------------------- | ------------------------------------------- | ---------------------------- | ---------------------------------------------------------------------- |
| `list_projects`            | `projects-lite`                             | `projects/`                  | lite-to-full fallback                                                  |
| `get_workspace_members`    | `members-lite`                              | `members/`                   | lite-to-full fallback                                                  |
| `get_project_members`      | `project-members-lite`                      | `project-members/`           | lite-to-full fallback                                                  |
| `list_cycles`              | lite `cycles`                               | `cycles/`                    | lite-to-full fallback                                                  |
| `list_modules`             | lite `modules`                              | `modules/`                   | lite-to-full fallback                                                  |
| `list_work_item_relations` | older SDK used `issues/.../issue-relation/` | `work-items/{id}/relations/` | current SDK path matches CE; remaining break is Category 3 model shape |

### 🐛 Category 3 — Endpoint works but the SDK model fails

| MCP tool                            | Problem                                                                        | Fix                                         |
| ----------------------------------- | ------------------------------------------------------------------------------ | ------------------------------------------- |
| `list_work_item_activities`         | CE returns fractional `epoch`; SDK model required `int`                        | local CE model uses `float`                 |
| `retrieve_work_item` with assignees | CE returns bare UUIDs rather than `UserLite`/`Label`                           | always expand `assignees,labels`            |
| `search_work_items`                 | CE returns integer `sequence_id`                                               | fixed by SDK 0.2.19; verified with a result |
| `list_work_item_relations`          | CE returns `{project_id, issue_id}` objects per group; SDK expects `list[str]` | local CE model + `_get` bypass (PMCP-11)    |

### 🚫 Category 2 — Not available in CE

No route exists in either the public or app API for `get_features`,
`update_workspace_features`, `update_project_features`, roles, initiatives,
milestones, `count_work_items`, work-item relation definitions, work logs,
project work-log summary, work-item types, work-item property values, or
work-item-to-page links (`attach_page_to_work_item`, `list_work_item_pages`,
and `detach_page_from_work_item`).

These tools are hidden from CE discovery through `CE_UNAVAILABLE_TOOLS` rather
than exposed to return 404. Re-evaluate an item only if a usable CE route is
identified.

### 🔑 Category 4 — Session-only app API

The following capabilities exist only under CE's session-authenticated app API
(`/api/`, without `/v1`). It requires a browser session and rejects PATs with
401:

| MCP tool                   | CE app endpoint                                                                 | Scope                                                        |
| -------------------------- | ------------------------------------------------------------------------------- | ------------------------------------------------------------ | ----------------------------------------------- | ------------ |
| `manage_work_item_archive` | `POST`/`DELETE` `…/issues/{id}/archive/`                                        | archive/unarchive completed or cancelled items               |
| `list_archived_work_items` | `GET` `…/archived-issues/`                                                      | —                                                            |
| `page(action="list"        | "retrieve"                                                                      | "create")`                                                   | `…/projects/{id}/pages/`                        | project only |
| `page(action="update")`    | `PATCH …/projects/{id}/pages/{page_id}/` plus the description route when needed | project only; applies name then content                      |
| `page(action="archive"     | "unarchive")`                                                                   | `POST` / `DELETE` `…/projects/{id}/pages/{page_id}/archive/` | project only; Cloud uses equivalent SDK methods |
| `page(action="delete")`    | `DELETE …/projects/{id}/pages/{page_id}/`                                       | page must already be archived                                |

Page operations are served by the `page(action=...)` resource tool. The
previous per-operation names (`list_pages`, `create_page`, `update_page`,
`update_page_content`, …) remain callable as compatibility aliases but are
hidden from discovery by `PlaneToolVisibilityMiddleware` — the same migration
pattern as the official Plane MCP. Without session credentials on CE, the
`page` tool is hidden as well, and direct calls fail fast with a clear
credentials error from `page_backends.get_page_backend` instead of a cryptic
401/404.

`plane_mcp/app_session.py` provides an opt-in bridge. It logs into the app with
CSRF plus `/auth/sign-in/`, keeps the `session-id` cookie, and routes only these
operations through the app API when session credentials are configured
(`PLANE_SESSION_EMAIL` + `PLANE_SESSION_PASSWORD`, or
`PLANE_SESSION_COOKIE`). Without credentials, `CE_SESSION_TOOLS` stay hidden.
Cloud ignores those variables and uses SDK/PAT routes.

CE limitations: project pages only; no workspace pages and no work-item/page
links. CE creation saves title and metadata first, then writes
`description_html` through `/description/`, so a successful result never claims
that content was saved when that second operation failed.

### Page MVP evidence — 2026-09-03

A direct, no-retry probe against Plane CE **v1.4.1** at
`https://plane.chans.xyz` (workspace `space`, project `PMCP`) verified: list
200, create 201, retrieve 200, name PATCH 200, content PATCH 200, archive 200,
unarchive 204, and delete of an active page returning 400. Archive followed by
delete returned 204. The stdio integration test performs the same round trip
and cleans up its temporary page. These endpoints do not expose the CE version;
verify it before upgrading the target server.

For session writes, the client never automatically replays a request after a
401, 403, timeout, connection reset, or 5xx. The operation might already have
been applied. Errors preserve the server response, including CSRF 403 messages;
read the resource before issuing a new write.

### Page hierarchy and collections probe — 2026-09-04

The same CE instance returned 404 (`{"error": "Page not found."}`) for the
session app route `GET /api/workspaces/space/collections/`; collections are
therefore Cloud-only for this target. A temporary page response omitted
`parent_id`, `collection_id`, and `page_collection_id`. Creating a temporary
child page with a valid temporary parent's ID in `parent_id` returned success,
but the subsequent read omitted `parent_id`: the parameter was silently
ignored. Both probes archived and deleted every temporary page.

Until a target CE version demonstrates different behavior, the MCP page surface
must not expose `parent_id` or `collection_id` for CE writes. Collection actions
must fail in backend pre-flight before any write is sent.

The runtime gate is `plane_mcp/ce_capabilities.py`: the default capability set
is the verified baseline (empty), and `PLANE_CE_CAPABILITIES` (comma-separated
keys, e.g. `pages.parent_id`) explicitly overrides it for a target you have
probed yourself. When a capability key is enabled, the CE create body forwards
the corresponding field instead of rejecting it.

---

## Completed work

- [x] **P1 — lite-to-full fallback**: `lite_or_fallback` corrects
      `list_projects`, workspace/project members, cycles, and modules. Inspired by
      upstream PR #173 and extended to the member tools.
- [x] **P2 — relations**: list and create use
      `work-items/{id}/relations/`. The tested CE stable version has no deletion
      route, so removal fails explicitly rather than calling a 404 endpoint.
- [x] **P3 — model fixes**: a local fractional-epoch model, automatic
      assignee/label expansion, and validation that SDK 0.2.19 accepts CE's integer
      `sequence_id`.
- [x] **P4 — clean Category 2 hiding** through `CE_UNAVAILABLE_TOOLS`.
- [x] **P7 — app-session bridge**: unlocks work-item archive and project pages
      through the app API when session credentials are configured. Tools use
      two-tier discovery: `CE_SESSION_TOOLS` are hidden unless a session is
      configured.

## Remaining planned work

- [ ] **P6 — selected upstream improvements**: `PLANE_MCP_MODULES` (PR #81,
      discovery filtering), `advanced_search` (PR #88), automatic assignee
      expansion (PR #80), JSON-string parameter normalization (PR #76), and
      host/port plus `/healthz` (PR #137).

## Candidate upstream work to adapt

The fork is based on the Python `plane_mcp/` implementation after its rewrite,
so Python pull requests can generally be adapted directly; older TypeScript
pull requests cannot.

| Upstream PR             | Capability                                  | Priority |
| ----------------------- | ------------------------------------------- | -------- |
| **#173** `refract99`    | lite-to-full fallback                       | **P1**   |
| **#161** `HellCatVN`    | self-hosted milestone-unavailable decorator | P4       |
| **#81** `enesdemir`     | `PLANE_MCP_MODULES` discovery filter        | P6       |
| **#88** `lifeiscontent` | structured `advanced_search_work_items`     | P6       |
| **#80** `Quentin-M`     | automatic assignee expansion                | P3/P6    |
| **#76** `ej31`          | normalize JSON-string list parameters       | P6       |
| **#137** `Maziak2520`   | environment host/port and `/healthz`        | P6       |
| **#117** `151813125`    | read work-item property values              | P5/P6    |
| **#62** `1nk1`          | page list/search/update/delete tools        | P5       |

Related CE issues: #169/#170/#172 (lite 404), #98 (assignees), #136 (search
`q` versus `search`), #163 (pages under `/api/v1`), #131 (PAT HTTP without
OAuth), and #102/#29 (too many tools).
