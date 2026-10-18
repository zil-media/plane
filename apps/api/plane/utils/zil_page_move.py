# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Move a page and everything under it to another project of the workspace, and the clients
folders to the brands' projects with it (phase 6 of brands).

A page belongs to a project only through its `ProjectPage` row; the tree is `Page.parent`, which
knows nothing of projects. Moving a subtree is therefore: its pages leave every project they were in
and join the destination, its root goes to the destination's top level, and the rows that point at
the old project follow (files and images, labels, favourites, recent visits). `moved_to_project` is
left on each page so a link to the old place can be sent to the new one.

Work items never move (decision 7 of the brands design): their history stays in the BU's project.
"""

# Python imports
import json
import logging
from collections import Counter

# Django imports
from django.db import transaction
from django.utils import timezone

# Module imports
from plane.db.models import (
    FileAsset,
    Label,
    Page,
    PageLabel,
    PageZilClientLink,
    ProjectMember,
    ProjectPage,
    UserFavorite,
    UserRecentVisit,
    Workspace,
    ZilBrandProject,
    ZilClientsRoot,
)
from plane.utils.page_tree import get_descendant_ids, next_child_sort_order

logger = logging.getLogger("plane.zil.page_move")

BRAND_FOLDER_NAME = "Documentos"


def _soft_delete(queryset):
    # an UPDATE, not Model.delete(): that one queues a Celery task per row
    return queryset.update(deleted_at=timezone.now())


def _label_in(project, label, cache):
    """The destination project's label with the same name, made when it has none."""
    key = label.name.strip().lower()
    if key not in cache:
        existing = Label.objects.filter(project_id=project.id, name__iexact=label.name.strip()).first()
        if existing is None:
            existing = Label(
                project_id=project.id,
                workspace_id=project.workspace_id,
                name=label.name.strip(),
                color=label.color,
                description=label.description,
            )
            existing.save(disable_auto_set_user=True)
        cache[key] = existing
    return cache[key]


def move_page_subtree(root, destination, rename_root=None):
    """Move `root` and its descendants to the project `destination`. Returns what moved and what
    needs a person (private pages whose owner is not in the destination)."""
    ids = [root.id, *get_descendant_ids(root.id)]
    member_ids = set(
        ProjectMember.objects.filter(project_id=destination.id, is_active=True).values_list("member_id", flat=True)
    )
    report = {"pages": len(ids), "assets": 0, "labels": 0, "favorites": 0, "unreachable_private": []}

    # the pages leave every project they were in: a page in two brands would mix them
    _soft_delete(ProjectPage.objects.filter(page_id__in=ids).exclude(project_id=destination.id))
    present = set(
        ProjectPage.objects.filter(page_id__in=ids, project_id=destination.id).values_list("page_id", flat=True)
    )
    for page_id in ids:
        if page_id not in present:
            ProjectPage(workspace_id=destination.workspace_id, project_id=destination.id, page_id=page_id).save(
                disable_auto_set_user=True
            )

    root.parent_id = None
    root.sort_order = next_child_sort_order(None, destination.id)
    fields = ["parent", "sort_order", "updated_at"]
    if rename_root:
        root.name = rename_root
        fields.append("name")
    root.save(update_fields=fields)
    Page.objects.filter(pk__in=ids).update(moved_to_project=destination.id)

    # embedded images and attachments are fetched through their project: they follow
    report["assets"] = (
        FileAsset.objects.filter(page_id__in=ids).exclude(project_id=destination.id).update(project_id=destination.id)
    )

    # labels are per project: the same name in the destination (made if missing)
    cache = {}
    for page_label in PageLabel.objects.filter(page_id__in=ids).select_related("label"):
        if page_label.label.project_id == destination.id:
            continue
        page_label.label = _label_in(destination, page_label.label, cache)
        page_label.save(update_fields=["label", "updated_at"])
        report["labels"] += 1

    # favourites and recent visits follow the page; those of people outside the destination go
    favorites = UserFavorite.objects.filter(entity_type="page", entity_identifier__in=ids)
    report["favorites"] = favorites.filter(user_id__in=member_ids).update(project_id=destination.id)
    favorites.exclude(user_id__in=member_ids).delete(soft=False)
    visits = UserRecentVisit.objects.filter(entity_name="page", entity_identifier__in=ids)
    visits.filter(user_id__in=member_ids).update(project_id=destination.id)
    visits.exclude(user_id__in=member_ids).delete(soft=False)

    for page_id, name, owner_email in (
        Page.objects.filter(pk__in=ids, access=Page.PRIVATE_ACCESS, deleted_at__isnull=True)
        .exclude(owned_by_id__in=member_ids)
        .values_list("id", "name", "owned_by__email")
    ):
        report["unreachable_private"].append({"page_id": str(page_id), "name": name, "owner": owner_email})
    return report


def moved_page_project(slug, page_id, user):
    """The project a moved page now lives in, when `user` can open it there; else None."""
    page = (
        Page.objects.filter(pk=page_id, workspace__slug=slug, moved_to_project__isnull=False)
        .values("moved_to_project", "access", "owned_by_id")
        .first()
    )
    if page is None or (page["access"] == Page.PRIVATE_ACCESS and page["owned_by_id"] != user.id):
        return None
    project_id = page["moved_to_project"]
    in_project = ProjectPage.objects.filter(page_id=page_id, project_id=project_id, deleted_at__isnull=True).exists()
    is_member = ProjectMember.objects.filter(project_id=project_id, member=user, is_active=True).exists()
    return project_id if in_project and is_member else None


def _destination_for(workspace, client_id, client_brands, brand_projects, migration_project_factory):
    """(project, reason): the brand's project for a single-brand client, "Migración" for one with
    several, None when there is nowhere to go (no brand in the map, or no project for it here)."""
    brands = client_brands.get(client_id)
    if brands is None:
        return None, "client_not_in_map"
    live = [b for b in brands if str(b.get("status") or "active") == "active"] or brands
    if len(live) > 1:
        return migration_project_factory(), "multi_brand"
    if not live:
        return None, "client_without_brand"
    mapping = brand_projects.get(str(live[0].get("brandId") or "").lower())
    if mapping is None:
        return None, "brand_has_no_project_here"
    return mapping.project, "single_brand"


def migrate_workspace_client_pages(workspace, client_brands):
    """Move every client folder of the workspace to its brand's project (see the module docstring)
    and drop the "Clientes" folder. Returns the report; the caller decides whether to keep it."""
    from plane.utils.zil_brand_projects import ensure_migration_project

    brand_projects = {
        m.zil_brand_id: m
        for m in ZilBrandProject.objects.filter(
            workspace_id=workspace.id,
            kind=ZilBrandProject.BRAND_KIND,
            project__deleted_at__isnull=True,
        ).select_related("project")
    }
    migration = {}

    def migration_project():
        if "project" not in migration:
            migration["project"] = ensure_migration_project(workspace)
        return migration["project"]

    report = {"workspace": workspace.slug, "moved": [], "skipped": [], "roots": [], "totals": Counter()}
    links = (
        PageZilClientLink.objects.filter(workspace_id=workspace.id, page__deleted_at__isnull=True)
        .select_related("page", "project")
        .order_by("created_at")
    )
    for link in links:
        destination, reason = _destination_for(
            workspace, link.zil_client_id, client_brands, brand_projects, migration_project
        )
        entry = {
            "client_id": link.zil_client_id,
            "folder": link.page.name,
            "from_project": link.project.name,
            "reason": reason,
        }
        if destination is None:
            report["skipped"].append(entry)
            report["totals"]["skipped"] += 1
            continue
        # in a brand's project the folder is just its documents: its name was the client's
        rename = None if reason == "multi_brand" else BRAND_FOLDER_NAME
        moved = move_page_subtree(link.page, destination, rename_root=rename)
        PageZilClientLink.objects.filter(pk=link.pk).delete(soft=False)
        entry.update({"to_project": destination.name, **moved})
        report["moved"].append(entry)
        report["totals"]["folders"] += 1
        report["totals"]["pages"] += moved["pages"]
        report["totals"]["assets"] += moved["assets"]
        report["totals"]["unreachable_private"] += len(moved["unreachable_private"])
        if reason == "multi_brand":
            report["totals"]["to_migration"] += 1

    # the "Clientes" folder goes: what someone else put in it stays, at the top of its project
    for root in ZilClientsRoot.objects.filter(workspace_id=workspace.id).select_related("page"):
        page = root.page
        left = Page.objects.filter(parent_id=page.id, deleted_at__isnull=True)
        lifted = []
        for child in left:
            child.parent_id = None
            child.sort_order = next_child_sort_order(None, root.project_id)
            child.save(update_fields=["parent", "sort_order", "updated_at"])
            lifted.append(child.name)
        if page.deleted_at is None:
            Page.objects.filter(pk=page.id).update(deleted_at=timezone.now())
            _soft_delete(ProjectPage.objects.filter(page_id=page.id))
        report["roots"].append({"folder": page.name, "lifted_to_top": lifted})
        ZilClientsRoot.all_objects.filter(pk=root.pk).delete()
    report["totals"] = dict(report["totals"])
    if "project" in migration:
        report["migration_project"] = migration["project"].name
    return report


class _Rollback(Exception):
    pass


def migrate_client_pages(client_brands, workspace_slugs=None, apply=False):
    """Run the migration over the workspaces (all those with a clients folder by default).
    Without `apply` everything is done and rolled back, so the report is what would happen."""
    with_folders = set(PageZilClientLink.objects.values_list("workspace_id", flat=True)) | set(
        ZilClientsRoot.objects.values_list("workspace_id", flat=True)
    )
    workspaces = Workspace.objects.filter(id__in=with_folders)
    if workspace_slugs:
        workspaces = Workspace.objects.filter(slug__in=workspace_slugs)
    reports = []
    for workspace in workspaces.order_by("slug"):
        try:
            with transaction.atomic():
                reports.append(migrate_workspace_client_pages(workspace, client_brands))
                if not apply:
                    raise _Rollback()
        except _Rollback:
            pass
    return {"applied": bool(apply), "workspaces": reports}


def load_client_brand_map(path):
    """`{clientId: [{brandId, name, status}]}` from Zil's export (exportClientBrandMap.js)."""
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    clients = data.get("clients", data)
    return {str(k).lower(): v or [] for k, v in clients.items()}
