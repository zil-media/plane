"""Ad-hoc probe harness: drives the stdio MCP in-memory and calls tools,
recording which succeed and which fail (esp. 404s) against the local CE instance.

Run: export $(grep -vE '^\\s*#' .env.test.local | xargs) && \\
     FASTMCP_LOG_LEVEL=ERROR python tests/harness_probe.py
"""

import asyncio
import json
import os
import re

from fastmcp import Client

from plane_mcp.server import get_stdio_mcp

WS = os.environ["PLANE_WORKSPACE_SLUG"]

results = []  # (tool, status, detail)
ctx = {}  # discovered ids


def _data(r):
    return r.data if hasattr(r, "data") else r


def _jsonable(obj):
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if isinstance(obj, list):
        return [_jsonable(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    return obj


def _classify(exc: Exception) -> str:
    s = str(exc)
    m = re.search(r"\b(404|403|405|400|401|500|502)\b", s)
    if m:
        return f"HTTP {m.group(1)}"
    if "Not Found" in s or "not found" in s:
        return "404?"
    return type(exc).__name__


async def call(client, tool, args, note=""):
    try:
        r = await client.call_tool(tool, args)
        d = _jsonable(_data(r))
        results.append((tool, "OK", note))
        return d
    except Exception as e:
        results.append((tool, _classify(e), f"{note} :: {str(e)[:200]}"))
        return None


def _first_id(d, *keys):
    """Extract first item's id from a list/paginated response."""
    if d is None:
        return None
    items = d
    if isinstance(d, dict):
        items = d.get("results") or d.get("items") or d.get("data") or []
    if isinstance(items, list) and items:
        it = items[0]
        if isinstance(it, dict):
            for k in keys or ("id",):
                if it.get(k):
                    return it[k]
            return it.get("id")
    return None


async def main():
    mcp = get_stdio_mcp()
    async with Client(mcp) as client:
        tools = {t.name for t in await client.list_tools()}
        print(f"# {len(tools)} tools\n")

        # ---- Phase 1: workspace-level ----
        await call(client, "get_me", {})
        projs = await call(client, "list_projects", {})
        pid = _first_id(projs) or os.environ.get("PLANE_TEST_PROJECT_ID")
        ctx["project_id"] = pid
        await call(client, "get_workspace_members", {})
        await call(client, "get_features", {})
        await call(client, "list_roles", {})
        await call(client, "list_initiatives", {})
        await call(client, "list_pages", {})
        await call(client, "list_work_item_types", {})
        await call(client, "list_work_item_relation_definitions", {})
        await call(client, "get_pql_reference", {})
        await call(client, "count_work_items", {})
        await call(client, "search_work_items", {"query": "test"})

        if not pid:
            print("NO PROJECT FOUND — aborting deeper probes")
            _report()
            return

        # ---- Phase 2: project-level ----
        await call(client, "retrieve_project", {"project_id": pid})
        await call(client, "get_project_members", {"project_id": pid})
        await call(client, "get_features", {"project_id": pid}, "project scope")
        await call(client, "get_project_estimate", {"project_id": pid})
        await call(client, "get_project_worklog_summary", {"project_id": pid})
        cycles = await call(client, "list_cycles", {"project_id": pid})
        modules = await call(client, "list_modules", {"project_id": pid})
        labels = await call(client, "list_labels", {"project_id": pid})
        states = await call(client, "list_states", {"project_id": pid})
        milestones = await call(client, "list_milestones", {"project_id": pid})
        witems = await call(client, "list_work_items", {"project_id": pid})
        await call(client, "list_archived_work_items", {"project_id": pid})
        await call(client, "list_intake_work_items", {"project_id": pid})
        await call(client, "list_work_item_properties", {"project_id": pid})

        # ---- Phase 3: ensure a work item exists to probe sub-resources ----
        wid = _first_id(witems)
        if not wid:
            created = await call(
                client,
                "create_work_item",
                {"project_id": pid, "name": "PROBE work item (safe to delete)"},
                "auto-created for probing",
            )
            wid = created.get("id") if isinstance(created, dict) else None
        ctx["work_item_id"] = wid

        # ---- Phase 4: retrieve sub-resources by discovered ids ----
        sid = _first_id(states)
        if sid:
            await call(client, "retrieve_state", {"project_id": pid, "state_id": sid})
        lid = _first_id(labels)
        if lid:
            await call(client, "retrieve_label", {"project_id": pid, "label_id": lid})
        cid = _first_id(cycles)
        if cid:
            await call(client, "retrieve_cycle", {"project_id": pid, "cycle_id": cid})
            await call(client, "list_cycle_work_items", {"project_id": pid, "cycle_id": cid})
        mid = _first_id(modules)
        if mid:
            await call(client, "retrieve_module", {"project_id": pid, "module_id": mid})
            await call(client, "list_module_work_items", {"project_id": pid, "module_id": mid})
        msid = _first_id(milestones)
        if msid:
            await call(client, "retrieve_milestone", {"project_id": pid, "milestone_id": msid})

        # work item type
        wtypes = await call(client, "list_work_item_types", {"project_id": pid}, "project scope")
        wtid = _first_id(wtypes)
        if wtid:
            await call(client, "retrieve_work_item_type", {"work_item_type_id": wtid, "project_id": pid})

        if wid:
            await call(client, "retrieve_work_item", {"project_id": pid, "work_item_id": wid})
            await call(client, "list_work_item_activities", {"project_id": pid, "work_item_id": wid})
            await call(client, "list_work_item_comments", {"project_id": pid, "work_item_id": wid})
            await call(client, "list_work_item_links", {"project_id": pid, "work_item_id": wid})
            await call(client, "list_work_item_attachments", {"project_id": pid, "work_item_id": wid})
            await call(client, "list_work_item_relations", {"project_id": pid, "work_item_id": wid})
            await call(client, "list_work_logs", {"project_id": pid, "work_item_id": wid})
            await call(client, "list_work_item_pages", {"project_id": pid, "work_item_id": wid})

        _report()


def _report():
    print("\n===== PROBE RESULTS =====")
    ok = [r for r in results if r[1] == "OK"]
    bad = [r for r in results if r[1] != "OK"]
    for t, s, d in results:
        mark = "OK " if s == "OK" else f"!! {s}"
        line = f"{mark:12} {t}"
        if s != "OK":
            line += f"  <- {d}"
        print(line)
    print(f"\n{len(ok)} OK / {len(bad)} FAILED  (of {len(results)} probed)")
    print("context:", json.dumps(ctx))


if __name__ == "__main__":
    asyncio.run(main())
