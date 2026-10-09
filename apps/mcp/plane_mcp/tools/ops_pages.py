"""Zil Ops page content: read a page as block-annotated markdown and edit it block by block.

The edits run on the page's collaborative document in Ops, so they merge with whatever people with
the page open are typing, and only the touched blocks change.
"""

from __future__ import annotations

from typing import Any, Literal

from fastmcp import FastMCP
from pydantic import BaseModel, Field

from plane_mcp.client import get_plane_client_context
from plane_mcp.ops import OpsSession


class PageEditOp(BaseModel):
    """One edit. Which fields apply depends on ``op``; see edit_page."""

    op: Literal["replace_text", "replace_block", "insert", "delete", "move", "set_attrs", "replace_all"]
    find: str | None = Field(None, description="replace_text: exact plain text to find, inside one block")
    replace: str | None = Field(None, description="replace_text: replacement text ('' deletes the match)")
    markdown: bool | None = Field(None, description="replace_text: parse `replace` as inline markdown")
    all: bool | None = Field(None, description="replace_text: replace every match instead of requiring one")
    block: str | None = Field(
        None,
        description="Block ref from read_page (id prefix or #n): target of replace_block/delete/move/set_attrs, "
        "or the block that scopes replace_text",
    )
    through: str | None = Field(None, description="delete: last block of a range of siblings starting at `block`")
    content: str | None = Field(None, description="replace_block/insert/replace_all: markdown (editor HTML allowed)")
    after: str | None = Field(None, description="insert/move: put it right after this block ref")
    before: str | None = Field(None, description="insert/move: put it right before this block ref")
    at: Literal["start", "end"] | None = Field(None, description="insert/move: at the start or end of the page")
    scope: Literal["top"] | None = Field(
        None,
        description="insert/move: 'top' anchors on the top-level block holding after/before (e.g. after a list)",
    )
    attrs: dict[str, Any] | None = Field(
        None,
        description="set_attrs: e.g. {checked: true} on a task, {level: 2} on a heading, {language: 'ts'}, "
        "{textAlign: 'center'}",
    )

    def payload(self) -> dict[str, Any]:
        return self.model_dump(exclude_none=True)


def register_ops_page_tools(mcp: FastMCP) -> None:
    @mcp.tool()
    def search_pages(
        query: str = "",
        project_id: str | None = None,
        include_archived: bool = False,
    ) -> dict[str, Any]:
        """Find Zil Ops pages (documents) by title or content across the projects you can see.

        Returns up to 50 pages, newest first, with project, parent (page tree), whether it is a
        folder, and a text snippet around the match. An empty query lists recent pages.

        Args:
            query: Words to look for in page titles and content.
            project_id: Limit to one project.
            include_archived: Also return archived pages.
        """
        client, workspace_slug = get_plane_client_context()
        params: dict[str, Any] = {"q": query, "archived": str(include_archived).lower()}
        if project_id:
            params["project_id"] = project_id
        return OpsSession(client, workspace_slug).api("GET", "pages/search/", params=params)

    @mcp.tool()
    def read_page(
        page_id: str,
        project_id: str,
        offset: int = 0,
        limit: int = 0,
        blocks: list[str] | None = None,
    ) -> dict[str, Any]:
        """Read a Zil Ops page as markdown, one line per block, each with its block ref in a gutter.

        Format: ``<ref> | <markdown>``. Every top-level block and every list item is a block; the
        ref (an id prefix like ``3f2a91c0``, or ``#n`` for blocks without an id yet) is what
        edit_page takes. Continuation lines of a block have an empty gutter. Things markdown can't
        express (callouts, mentions, images, embeds, colors) appear as the editor's HTML; text
        alignment appears as a trailing ``{: align=center}``.

        Read before editing, and re-read only the part you need: use offset/limit for long pages
        (``total_blocks`` says how many there are) or ``blocks`` to fetch specific refs.

        Args:
            page_id: UUID of the page.
            project_id: UUID of the page's project.
            offset: Skip this many blocks.
            limit: Return at most this many blocks (0 = all).
            blocks: Only these block refs.
        """
        client, workspace_slug = get_plane_client_context()
        ops = OpsSession(client, workspace_slug)
        params: dict[str, Any] = {**ops.scope(project_id), "offset": offset}
        if limit:
            params["limit"] = limit
        if blocks:
            params["blocks"] = ",".join(blocks)
        return ops.live("GET", page_id, params=params)

    @mcp.tool()
    def edit_page(page_id: str, project_id: str, ops: list[PageEditOp]) -> dict[str, Any]:
        """Edit a Zil Ops page precisely, without rewriting it. Ops apply in order, all or nothing.

        Block refs come from read_page (id prefix or ``#n``; ``#n`` always means the page as read
        before this call). Prefer the smallest op that does the job:

        - ``replace_text {find, replace, block?, all?, markdown?}``: change words inside a block,
          keeping formatting around them. ``find`` is plain text (no markdown) within one block and
          must match once unless ``all`` is true; pass ``block`` to scope it. ``replace`` is plain
          text unless ``markdown`` is true (e.g. to add **bold** or a [link](url)). ``replace: ""``
          deletes the text.
        - ``replace_block {block, content}``: rewrite one block (keeps its ref). On a list item the
          content becomes item(s) of that list.
        - ``insert {content, after|before|at, scope?}``: add blocks. Next to a list item the content
          becomes list items; use ``scope: "top"`` to place it after/before the whole list instead.
          ``at: "start"|"end"`` for the page edges.
        - ``delete {block, through?}``: remove a block, or a range of siblings through ``through``.
        - ``move {block, after|before|at, scope?}``: relocate a block (items convert between list
          types).
        - ``set_attrs {block, attrs}``: toggle a task (``checked``), heading ``level``, code
          ``language``, ``textAlign``.
        - ``replace_all {content}``: replace the whole page (unchanged blocks keep their refs).

        ``content`` is markdown: headings, lists, ``- [ ] tasks``, tables, code fences, quotes,
        ``---``; editor HTML passes through for callouts, mentions, images.

        Returns a summary per op and the touched blocks as they are now (same format as read_page),
        so there is no need to re-read the page to check.

        Args:
            page_id: UUID of the page.
            project_id: UUID of the page's project.
            ops: The edits, applied in order.
        """
        client, workspace_slug = get_plane_client_context()
        session = OpsSession(client, workspace_slug)
        return session.live(
            "POST",
            f"{page_id}/edit",
            json={**session.scope(project_id), "ops": [op.payload() for op in ops]},
        )
