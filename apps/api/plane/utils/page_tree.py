# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Helpers for the project page tree (Page.parent hierarchy)."""

# Django imports
from django.db import connection
from django.db.models import Max

# Module imports
from plane.db.models import Page
from plane.utils.error_codes import ERROR_CODES

SORT_ORDER_STEP = 10000


class PageTreeError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message

    def as_response_data(self):
        return {"error_code": ERROR_CODES[self.code], "error_message": self.code, "error": self.message}


def set_archived_at_for_page_and_descendants(page_id, archived_at):
    """Archive (or restore with None) a page and its whole subtree. Returns the affected ids."""
    sql = """
    WITH RECURSIVE descendants AS (
        SELECT id FROM pages WHERE id = %s
        UNION ALL
        SELECT pages.id FROM pages, descendants
        WHERE pages.parent_id = descendants.id AND pages.deleted_at IS NULL
    )
    UPDATE pages SET archived_at = %s WHERE id IN (SELECT id FROM descendants)
    RETURNING id;
    """
    with connection.cursor() as cursor:
        cursor.execute(sql, [page_id, archived_at])
        return [row[0] for row in cursor.fetchall()]


def get_descendant_ids(page_id):
    """All live descendants of a page (the page itself excluded)."""
    sql = """
    WITH RECURSIVE descendants AS (
        SELECT id FROM pages WHERE parent_id = %s AND deleted_at IS NULL
        UNION ALL
        SELECT pages.id FROM pages, descendants
        WHERE pages.parent_id = descendants.id AND pages.deleted_at IS NULL
    )
    SELECT id FROM descendants;
    """
    with connection.cursor() as cursor:
        cursor.execute(sql, [page_id])
        return [row[0] for row in cursor.fetchall()]


def get_ancestor_ids(page_id):
    """Ancestors of a page ordered root -> direct parent (the page itself excluded)."""
    sql = """
    WITH RECURSIVE ancestors AS (
        SELECT parent_id AS id, 1 AS lvl FROM pages WHERE id = %s
        UNION ALL
        SELECT pages.parent_id, ancestors.lvl + 1 FROM pages, ancestors
        WHERE pages.id = ancestors.id AND ancestors.lvl < 64
    )
    SELECT id FROM ancestors WHERE id IS NOT NULL ORDER BY lvl DESC;
    """
    with connection.cursor() as cursor:
        cursor.execute(sql, [page_id])
        return [row[0] for row in cursor.fetchall()]


def get_subtree_height(page_id):
    """Number of levels in the subtree rooted at page_id (a leaf is 1)."""
    sql = """
    WITH RECURSIVE subtree AS (
        SELECT id, 1 AS depth FROM pages WHERE id = %s
        UNION ALL
        SELECT pages.id, subtree.depth + 1 FROM pages, subtree
        WHERE pages.parent_id = subtree.id AND pages.deleted_at IS NULL AND subtree.depth < 64
    )
    SELECT COALESCE(MAX(depth), 1) FROM subtree;
    """
    with connection.cursor() as cursor:
        cursor.execute(sql, [page_id])
        return cursor.fetchone()[0]


def validate_new_parent(page, parent_id, project_id, slug, user=None):
    """Validate moving `page` (None for a page being created) under `parent_id`.

    Returns the parent Page, or None when the target is the project root.
    Raises PageTreeError when the move is not allowed.
    """
    if not parent_id:
        return None

    parent = Page.objects.filter(
        pk=parent_id,
        workspace__slug=slug,
        projects__id=project_id,
        project_pages__deleted_at__isnull=True,
    ).first()
    if parent is None or (
        user is not None and parent.access == Page.PRIVATE_ACCESS and parent.owned_by_id != user.id
    ):
        raise PageTreeError("PAGE_PARENT_INVALID", "Parent page not found in this project")

    if parent.archived_at is not None:
        raise PageTreeError("PAGE_PARENT_INVALID", "Parent page is archived")

    subtree_height = 1
    if page is not None:
        if str(parent.id) == str(page.id) or parent.id in get_descendant_ids(page.id):
            raise PageTreeError("PAGE_TREE_CYCLE", "A page cannot be moved inside itself")
        subtree_height = get_subtree_height(page.id)

    # parent depth = its ancestors + itself; the moved subtree hangs below it
    if len(get_ancestor_ids(parent.id)) + 1 + subtree_height > Page.MAX_TREE_DEPTH:
        raise PageTreeError("PAGE_TREE_DEPTH", "Maximum page nesting depth exceeded")

    return parent


def next_child_sort_order(parent_id, project_id):
    """Sort order that places a new node last among its siblings."""
    max_sort_order = Page.objects.filter(
        parent_id=parent_id,
        projects__id=project_id,
        project_pages__deleted_at__isnull=True,
    ).aggregate(max_sort=Max("sort_order"))["max_sort"]
    if max_sort_order is None:
        return Page.DEFAULT_SORT_ORDER
    return max_sort_order + SORT_ORDER_STEP
