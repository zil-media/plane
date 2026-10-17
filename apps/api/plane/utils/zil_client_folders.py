# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""One folder per Zil client under the workspace's "Clientes" folder (ZilClientsRoot).

Zil sends a workspace's full client roster (the active and paused clients its Business
Units own or work on). Nobody sets anything up in Ops: the first roster with clients gives
the workspace its "Clientes" folder (an existing top-level "Clientes" folder is adopted;
otherwise one is created at the root of the BU's main project), and every roster is then
applied to it:

- a client with no folder linked in that project gets one: a public sub-folder of the root,
  owned by the Zil service user (also under an adopted folder, which stays its maker's), linked
  with `auto_created=True`;
- a folder linked by hand anywhere in the project is respected: it is only refreshed;
- an auto-created folder is renamed when the client is, unless someone renamed it by hand;
- with `authoritative=True`, an auto-created folder whose client left the roster is archived
  (never deleted) and restored if the client comes back. Archiving a folder archives what is
  inside it, so any other client's folder someone moved in there is first lifted back under the
  root: a client's folder only ever goes with its own client.

Idempotent: applying the same roster twice changes nothing.

Ordered: Zil sends from two places (the durable job and the 30-minute cron) that are not
serialized, so a roster computed earlier can be delivered after a newer one and, applied, would
undo it (archive the client just added). Each roster carries `computed_at` (the instant Zil
started reading, so everything committed before it is in the roster) and a root keeps in
`synced_at` the `computed_at` of the last roster it applied: an older one is ignored, also when
the folder was replaced in between (a roster does not rebuild a clients folder that a newer one
already applied to). A roster without `computed_at` always applies and stamps the root with
Plane's own clock.
"""

# Python imports
from datetime import datetime

# Django imports
from django.db import connection, transaction
from django.db.models import Max
from django.utils import timezone

# Module imports
from plane.authentication.utils.zil_provisioning import get_service_user
from plane.db.models import Page, PageZilClientLink, Project, ProjectPage, Workspace, ZilClientsRoot
from plane.utils.page_tree import (
    get_descendant_ids,
    next_child_sort_order,
    set_archived_at_for_page_and_descendants,
)
from plane.utils.zil_client import apply_zil_client_fields, is_valid_client_id


CLIENTS_FOLDER_NAME = "Clientes"


def client_folder_name(client):
    return ((client.get("alias") or "").strip() or (client.get("companyName") or "").strip() or "Cliente")[:255]


def live_roots(workspace_id):
    return ZilClientsRoot.objects.filter(
        workspace_id=workspace_id,
        page__deleted_at__isnull=True,
        page__archived_at__isnull=True,
        page__kind=Page.FOLDER_KIND,
        # a folder inside an archived or deleted project is out of reach: the workspace gets a new one
        project__archived_at__isnull=True,
        project__deleted_at__isnull=True,
    ).select_related("page", "project")


def _is_stale(computed_at, synced_at):
    return computed_at is not None and synced_at is not None and computed_at < synced_at


def _last_applied_at(workspace_id):
    """The newest roster time any clients root of the workspace applied, replaced (deleted) roots included."""
    return ZilClientsRoot.all_objects.filter(workspace_id=workspace_id).aggregate(last=Max("synced_at"))["last"]


def _create(model, **fields):
    """Insert a row keeping the audit users given. The sync has no request user, which a plain
    save would read as "nobody" and blank created_by / updated_by with."""
    row = model(**fields)
    row.save(disable_auto_set_user=True)
    return row


def _lock_workspace(workspace_id):
    """One push at a time per workspace until the transaction ends.

    A push reads what exists and then creates what is missing: two at once both see "no clients
    folder / no folder for this client" and the second one dies on the unique constraints.
    """
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [f"zil-client-folders:{workspace_id}"])


def _main_project(workspace):
    """The BU's own project (named like the workspace), else the workspace's oldest live project."""
    projects = list(Project.objects.filter(workspace_id=workspace.id, archived_at__isnull=True).order_by("created_at"))
    name = (workspace.name or "").strip().lower()
    return next((p for p in projects if (p.name or "").strip().lower() == name), projects[0] if projects else None)


def ensure_clients_root(workspace, owner):
    """The workspace's clients folder, adopting or creating it (owned by `owner`) when there is none.
    None without projects."""
    root = live_roots(workspace.id).first()
    if root is not None:
        return root
    # a clients folder that was archived or deleted is replaced: Zil decides that it exists (R3)
    ZilClientsRoot.objects.filter(workspace_id=workspace.id).delete()

    folder = (
        Page.objects.filter(
            workspace_id=workspace.id,
            kind=Page.FOLDER_KIND,
            parent__isnull=True,
            name__iexact=CLIENTS_FOLDER_NAME,
            access=Page.PUBLIC_ACCESS,
            archived_at__isnull=True,
            project_pages__deleted_at__isnull=True,
            project_pages__project__archived_at__isnull=True,
            zil_client_link__isnull=True,
        )
        .order_by("created_at")
        .first()
    )
    if folder is not None:
        project_id = folder.project_pages.filter(deleted_at__isnull=True).values_list("project_id", flat=True).first()
    else:
        project = _main_project(workspace)
        if project is None:
            return None
        folder = _create(
            Page,
            name=CLIENTS_FOLDER_NAME,
            kind=Page.FOLDER_KIND,
            access=Page.PUBLIC_ACCESS,
            owned_by_id=owner.id,
            workspace_id=workspace.id,
            description_json={},
            description_binary=None,
            description_html="<p></p>",
            sort_order=next_child_sort_order(None, project.id),
            created_by_id=owner.id,
            updated_by_id=owner.id,
        )
        _create(
            ProjectPage,
            workspace_id=workspace.id,
            project_id=project.id,
            page_id=folder.id,
            created_by_id=owner.id,
            updated_by_id=owner.id,
        )
        project_id = project.id
    # a project has one clients folder: a stale root of that project goes first
    ZilClientsRoot.all_objects.filter(page_id=folder.id).delete()
    root = _create(
        ZilClientsRoot,
        workspace_id=workspace.id,
        project_id=project_id,
        page_id=folder.id,
        created_by_id=owner.id,
    )
    return ZilClientsRoot.objects.select_related("page", "project").get(pk=root.pk)


def _create_client_folder(root, client, owner):
    name = client_folder_name(client)
    page = _create(
        Page,
        name=name,
        kind=Page.FOLDER_KIND,
        parent_id=root.page_id,
        access=Page.PUBLIC_ACCESS,
        owned_by_id=owner.id,
        workspace_id=root.workspace_id,
        description_json={},
        description_binary=None,
        description_html="<p></p>",
        sort_order=next_child_sort_order(root.page_id, root.project_id),
        created_by_id=owner.id,
        updated_by_id=owner.id,
    )
    _create(
        ProjectPage,
        workspace_id=root.workspace_id,
        project_id=root.project_id,
        page_id=page.id,
        created_by_id=owner.id,
        updated_by_id=owner.id,
    )
    link = PageZilClientLink(
        workspace_id=root.workspace_id,
        project_id=root.project_id,
        page_id=page.id,
        zil_client_id=client["id"],
        auto_created=True,
        auto_name=name,
        created_by_id=owner.id,
        updated_by_id=owner.id,
    )
    apply_zil_client_fields(link, client)
    link.save(disable_auto_set_user=True)
    return link


def _apply_to_root(root, clients_by_id, authoritative, stats, owner):
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
            _create_client_folder(root, client, owner)
            stats["created"] += 1
            continue

        apply_zil_client_fields(link, client)
        page = link.page
        if link.auto_created:
            if page.archived_at is not None:
                # restored under the root unless it sits in a live folder someone moved it to: a parent
                # that is archived, deleted (its children moved up to the top level) or gone leaves it adrift
                if not (page.parent_id and Page.objects.filter(pk=page.parent_id, archived_at__isnull=True).exists()):
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
        link.save(disable_auto_set_user=True)

    if not authoritative:
        return
    for client_id, link in links.items():
        if client_id in clients_by_id or not link.auto_created:
            continue
        if link.page.deleted_at is None and link.page.archived_at is None:
            _lift_other_clients_folders(root, link, links)
            set_archived_at_for_page_and_descendants(link.page_id, datetime.now())
            stats["archived"] += 1


def _lift_other_clients_folders(root, leaving, links):
    """Move the folders of other clients out of `leaving`'s folder, back under the root.

    Archiving a folder archives its whole subtree, and people do move a client's folder into
    another's (auto-created ones come back on the next push, but a hand-linked one would stay
    archived). Only the outermost ones move: a client's folder nested in another client's folder
    that is itself lifted keeps its place there.
    """
    inside = set(get_descendant_ids(leaving.page_id))
    other_links = [other for other in links.values() if other.page_id in inside]
    if not other_links:
        return
    folder_ids = {other.page_id for other in other_links}
    parent_of = dict(Page.objects.filter(pk__in=inside).values_list("id", "parent_id"))
    for other in other_links:
        ancestor = parent_of.get(other.page_id)
        nested_in_another_client = False
        for _ in range(len(parent_of)):
            if ancestor is None or ancestor == leaving.page_id:
                break
            if ancestor in folder_ids:
                nested_in_another_client = True
                break
            ancestor = parent_of.get(ancestor)
        if nested_in_another_client:
            continue
        page = other.page
        page.parent_id = root.page_id
        page.sort_order = next_child_sort_order(root.page_id, root.project_id)
        page.save(update_fields=["parent", "sort_order", "updated_at"])


def apply_client_folders(workspace_id, clients, authoritative, computed_at=None):
    """Apply a workspace's client roster to its clients folder (created on the first one). Returns counters.

    `computed_at` (aware datetime): when Zil started computing the roster. A root that already
    applied a roster computed after it skips this one (counted in `stale`).
    """
    clients_by_id = {}
    for client in clients or []:
        client_id = str(client.get("id") or "").strip().lower()
        if is_valid_client_id(client_id):
            clients_by_id[client_id] = {**client, "id": client_id}

    stats = {"roots": 0, "created": 0, "renamed": 0, "archived": 0, "restored": 0, "stale": 0}
    # what the sync makes is the service user's, not whoever made the folder it adopted
    owner = get_service_user() if clients_by_id else None
    with transaction.atomic():
        _lock_workspace(workspace_id)
        # no clients yet: no folder to hold them
        if clients_by_id:
            # a new clients folder has no stamp of its own: an older roster must not be the one that
            # replaces the folder a newer roster already applied to, then run on it as if it were first
            if not live_roots(workspace_id).exists() and _is_stale(computed_at, _last_applied_at(workspace_id)):
                stats["stale"] += 1
                return stats
            ensure_clients_root(Workspace.objects.get(pk=workspace_id), owner)
        for root in live_roots(workspace_id):
            # checked under the lock, so it reads what the push before this one stamped
            if _is_stale(computed_at, root.synced_at):
                stats["stale"] += 1
                continue
            _apply_to_root(root, clients_by_id, authoritative, stats, owner)
            root.synced_at = computed_at or timezone.now()
            root.save(update_fields=["synced_at", "updated_at"])
            stats["roots"] += 1
    return stats
