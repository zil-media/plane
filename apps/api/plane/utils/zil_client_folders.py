# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""One folder per Zil client under each project's clients root (ZilClientsRoot).

Zil sends a workspace's full client roster (the active and paused clients its Business
Units own or work on); this applies it to every clients root of that workspace:

- a client with no folder linked in that project gets one: a public sub-folder of the root,
  owned by the root's owner, linked with `auto_created=True`;
- a folder linked by hand anywhere in the project is respected: it is only refreshed;
- an auto-created folder is renamed when the client is, unless someone renamed it by hand;
- with `authoritative=True`, an auto-created folder whose client left the roster is archived
  (never deleted) and restored if the client comes back.

Idempotent: applying the same roster twice changes nothing.
"""

# Python imports
from datetime import datetime

# Django imports
from django.db import transaction
from django.utils import timezone

# Module imports
from plane.db.models import Page, PageZilClientLink, ProjectPage, ZilClientsRoot
from plane.utils.page_tree import next_child_sort_order, set_archived_at_for_page_and_descendants
from plane.utils.zil_client import apply_zil_client_fields, is_valid_client_id


def client_folder_name(client):
    return ((client.get("alias") or "").strip() or (client.get("companyName") or "").strip() or "Cliente")[:255]


def live_roots(workspace_id):
    return ZilClientsRoot.objects.filter(
        workspace_id=workspace_id,
        page__deleted_at__isnull=True,
        page__archived_at__isnull=True,
        page__kind=Page.FOLDER_KIND,
    ).select_related("page", "project")


def _create_client_folder(root, client):
    name = client_folder_name(client)
    page = Page.objects.create(
        name=name,
        kind=Page.FOLDER_KIND,
        parent_id=root.page_id,
        access=Page.PUBLIC_ACCESS,
        owned_by_id=root.page.owned_by_id,
        workspace_id=root.workspace_id,
        description_json={},
        description_binary=None,
        description_html="<p></p>",
        sort_order=next_child_sort_order(root.page_id, root.project_id),
        created_by_id=root.page.owned_by_id,
        updated_by_id=root.page.owned_by_id,
    )
    ProjectPage.objects.create(
        workspace_id=root.workspace_id,
        project_id=root.project_id,
        page_id=page.id,
        created_by_id=root.page.owned_by_id,
        updated_by_id=root.page.owned_by_id,
    )
    link = PageZilClientLink(
        workspace_id=root.workspace_id,
        project_id=root.project_id,
        page_id=page.id,
        zil_client_id=client["id"],
        auto_created=True,
        auto_name=name,
        created_by_id=root.page.owned_by_id,
        updated_by_id=root.page.owned_by_id,
    )
    apply_zil_client_fields(link, client)
    link.save()
    return link


def _apply_to_root(root, clients_by_id, authoritative, stats):
    links = {
        link.zil_client_id: link
        for link in PageZilClientLink.objects.filter(project_id=root.project_id).select_related("page")
    }

    for client_id, client in clients_by_id.items():
        link = links.get(client_id)
        # a link whose folder was deleted some other way is stale: drop it, the client gets a new folder
        if link is not None and link.page.deleted_at is not None:
            link.delete()
            link = None
        if link is None:
            _create_client_folder(root, client)
            stats["created"] += 1
            continue

        apply_zil_client_fields(link, client)
        page = link.page
        if link.auto_created:
            if page.archived_at is not None:
                # restored under the root even if its old parent stayed archived
                if page.parent_id and Page.objects.filter(pk=page.parent_id, archived_at__isnull=False).exists():
                    page.parent_id = root.page_id
                    page.save(update_fields=["parent", "updated_at"])
                set_archived_at_for_page_and_descendants(page.id, None)
                stats["restored"] += 1
            name = client_folder_name(client)
            if name != link.auto_name and page.name == link.auto_name:
                page.name = name
                page.save(update_fields=["name", "updated_at"])
                stats["renamed"] += 1
            link.auto_name = name if page.name == name else link.auto_name
        link.save()

    if not authoritative:
        return
    for client_id, link in links.items():
        if client_id in clients_by_id or not link.auto_created:
            continue
        if link.page.deleted_at is None and link.page.archived_at is None:
            set_archived_at_for_page_and_descendants(link.page_id, datetime.now())
            stats["archived"] += 1


def apply_client_folders(workspace_id, clients, authoritative):
    """Apply a workspace's client roster to all its clients roots. Returns counters."""
    clients_by_id = {}
    for client in clients or []:
        client_id = str(client.get("id") or "").strip().lower()
        if is_valid_client_id(client_id):
            clients_by_id[client_id] = {**client, "id": client_id}

    stats = {"roots": 0, "created": 0, "renamed": 0, "archived": 0, "restored": 0}
    for root in live_roots(workspace_id):
        with transaction.atomic():
            _apply_to_root(root, clients_by_id, authoritative, stats)
            root.synced_at = timezone.now()
            root.save(update_fields=["synced_at", "updated_at"])
        stats["roots"] += 1
    return stats
