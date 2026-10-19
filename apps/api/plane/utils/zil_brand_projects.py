# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""One private project per Zil brand (Marca) in each Business Unit workspace that works it.

Zil Workspace pushes, per workspace, the full list of brands that workspace works and who works
on each one (POST /api/zil/sync/brand-projects/). Nobody sets anything up in Ops:

- a brand with no project gets one: private (`network = 0`), with the brand's color, the default
  states (and the studio's, with `template: "studio"`), and no agents (they join a brand only when
  someone adds them). A project of the workspace already named like the brand is adopted instead
  of making a second one (the studio already made one project per client);
- a brand is known by its id, never by its name: renaming the brand renames the project, unless
  someone renamed the project by hand. The identifier (the `KFC` of `KFC-123`) is given once and
  never changes;
- a brand marked archived, or (with `authoritative`) one that left the list, archives its project
  (never deletes it); coming back restores it;
- who works on the brand is decided only in Zil: the members of the project are the list, applied
  as a difference (nobody is re-added or touched when nothing changed). Workspace admins (directors
  and Zil admins) are never added nor removed: they see everything and join a brand when they need
  to. People who never signed in to Ops are kept by email and join on their first sign-in.

Safe against a bad push: an authoritative but empty list archives nothing (it is a truncated
payload, not "no brands"), and one that would archive more than half of the workspace's brands
needs `force`. One brand that fails is reported and does not stop the others.

Ordered like the clients folders: each push carries `computed_at` and a workspace keeps the one of
the last roster it applied (`ZilBrandRoster`); an older one is ignored.
"""

# Python imports
import logging
import os
import re
import unicodedata

# Django imports
from django.db import connection, transaction
from django.utils import timezone

# Module imports
from plane.authentication.utils.zil_provisioning import get_service_user
from plane.db.models import (
    BotTypeEnum,
    Project,
    ProjectIdentifier,
    ProjectMember,
    ProjectMemberInvite,
    State,
    UserFavorite,
    Workspace,
    WorkspaceMember,
    ZilBrandMember,
    ZilBrandProject,
    ZilBrandRoster,
)
from plane.db.models.project import ProjectNetwork
from plane.db.models.state import DEFAULT_STATES
from plane.utils.studio_defaults import seed_studio_defaults
from plane.utils.zil_client import is_valid_client_id
from plane.utils.zil_managed import ZIL_PROJECT_NAME_FORBIDDEN

logger = logging.getLogger("plane.zil.brand_projects")

ADMIN_ROLE = 20
MEMBER_ROLE = 15
GUEST_ROLE = 5
BRAND_ROLES = {"member": MEMBER_ROLE, "guest": GUEST_ROLE}

DEFAULT_BRAND_ICON = "storefront"
MIGRATION_PROJECT_NAME = "Migración"
MIGRATION_IDENTIFIER = "MIGRA"
STUDIO_TEMPLATE = "studio"

COLOR_RE = re.compile(r"^#[0-9a-fA-F]{3,8}$")


def archive_fuse():
    """(min, fraction): a run archives at most `fraction` of the known brands, or `min` of them."""
    try:
        minimum = int(os.environ.get("ZIL_BRAND_ARCHIVE_MIN", "3"))
    except ValueError:
        minimum = 3
    try:
        fraction = float(os.environ.get("ZIL_BRAND_ARCHIVE_MAX_FRACTION", "0.5"))
    except ValueError:
        fraction = 0.5
    return minimum, fraction


def brand_project_name(raw):
    name = " ".join(ZIL_PROJECT_NAME_FORBIDDEN.sub("", str(raw or "")).split())
    return name[:255] or "Marca"


def _unique_name(workspace_id, base, brand_id, project_id=None):
    """`base`, or `base · XXXX` (the brand id's end, never the client) when another project of the
    workspace has it: two brands called "Santo" of different clients in one BU."""
    taken = Project.objects.filter(workspace_id=workspace_id, name=base)
    if project_id is not None:
        taken = taken.exclude(pk=project_id)
    if not taken.exists():
        return base
    suffix = f" · {brand_id[-4:].upper()}" if brand_id else " · Zil"
    return f"{base[: 255 - len(suffix)]}{suffix}"


def _identifier_base(name):
    folded = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    letters = re.sub(r"[^A-Za-z0-9]", "", folded).upper()
    return (letters or "MARCA")[:5]


def allocate_identifier(workspace_id, name):
    """A free identifier for a new project of the workspace, derived from its name."""
    base = _identifier_base(name)
    taken = set(Project.objects.filter(workspace_id=workspace_id).values_list("identifier", flat=True)) | set(
        ProjectIdentifier.objects.filter(workspace_id=workspace_id).values_list("name", flat=True)
    )
    taken = {str(t).upper() for t in taken}
    if base not in taken:
        return base
    for n in range(2, 10000):
        candidate = f"{base[: 12 - len(str(n))]}{n}"
        if candidate not in taken:
            return candidate
    raise ValueError("no identifier left")


def _logo_props(color):
    icon = {"name": DEFAULT_BRAND_ICON}
    if color:
        icon["color"] = color
    return {"in_use": "icon", "icon": icon}


def create_zil_project(workspace, name, identifier, owner, color=None, template=None):
    """A new private project with what `ProjectViewSet.create` gives one (identifier row, default
    states) except members and agents: Zil decides who is in it."""
    project = Project(
        workspace_id=workspace.id,
        name=name,
        identifier=identifier,
        network=ProjectNetwork.SECRET.value,
        logo_props=_logo_props(color),
        page_view=True,
        module_view=True,
        cycle_view=True,
    )
    project.save(created_by_id=owner.id)
    ProjectIdentifier.objects.create(name=project.identifier, project=project, workspace_id=workspace.id)
    State.objects.bulk_create(
        [
            State(
                name=state["name"],
                color=state["color"],
                project=project,
                sequence=state["sequence"],
                workspace=workspace,
                group=state["group"],
                default=state.get("default", False),
                created_by=owner,
            )
            for state in DEFAULT_STATES
        ]
    )
    if template == STUDIO_TEMPLATE:
        seed_studio_defaults(project=project, workspace=workspace, user=owner)
    return project


def _lock_workspace(workspace_id):
    """One roster at a time per workspace until the transaction ends."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [f"zil-brand-projects:{workspace_id}"])


def _is_stale(computed_at, synced_at):
    return computed_at is not None and synced_at is not None and computed_at < synced_at


def has_brand_roster(workspace_id):
    """Whether the workspace already gets its brands as projects (its clients folder is gone)."""
    return ZilBrandRoster.all_objects.filter(workspace_id=workspace_id).exists()


def _archive(project):
    project.archived_at = timezone.now()
    project.save(update_fields=["archived_at", "updated_at"])
    UserFavorite.objects.filter(project_id=project.id).delete()


def _restore(project):
    project.archived_at = None
    project.save(update_fields=["archived_at", "updated_at"])


def _parse_members(raw_members):
    desired = {}
    for member in raw_members or []:
        if not isinstance(member, dict):
            continue
        email = str(member.get("email") or "").strip().lower()
        if "@" not in email:
            continue
        role = BRAND_ROLES.get(str(member.get("role") or "member").strip().lower(), MEMBER_ROLE)
        # the same person twice keeps the higher role
        desired[email] = max(role, desired.get(email, 0))
    return desired


def _workspace_roles(workspace_id):
    """{email: (user_id, workspace role)} of the workspace's active human members."""
    return {
        email.lower(): (member_id, role)
        for email, member_id, role in WorkspaceMember.objects.filter(
            workspace_id=workspace_id, is_active=True, member__is_bot=False, member__is_active=True
        ).values_list("member__email", "member_id", "role")
    }


def _ensure_member(project, user_id, role):
    """Make `user_id` an active member of `project` with `role`. True when something changed."""
    membership = ProjectMember.objects.filter(project_id=project.id, member_id=user_id).first()
    if membership is None:
        # the model save (not bulk_create): it also makes the member's ProjectUserProperty
        ProjectMember(project=project, member_id=user_id, role=role, workspace_id=project.workspace_id).save(
            disable_auto_set_user=True
        )
        return True
    fields = []
    if not membership.is_active:
        membership.is_active = True
        fields.append("is_active")
    if membership.role != role:
        membership.role = role
        fields.append("role")
    if fields:
        membership.save(update_fields=[*fields, "updated_at"])
    return bool(fields)


def apply_members(mapping, raw_members, members_authoritative, stats, ws_roles=None):
    """Make the project's members the brand's team. Returns whether anything changed."""
    desired = _parse_members(raw_members)
    project = mapping.project
    ws_roles = _workspace_roles(project.workspace_id) if ws_roles is None else ws_roles
    changed = False

    # who Zil wants, by email: also those who never signed in, applied on their first sign-in
    stored = {row.email: row for row in ZilBrandMember.objects.filter(brand_project=mapping)}
    for email, role in desired.items():
        row = stored.get(email)
        if row is None:
            ZilBrandMember(brand_project=mapping, email=email, role=role).save(disable_auto_set_user=True)
        elif row.role != role:
            row.role = role
            row.save(update_fields=["role", "updated_at"])
    if members_authoritative:
        gone = [row.pk for email, row in stored.items() if email not in desired]
        if gone:
            ZilBrandMember.objects.filter(pk__in=gone).delete(soft=False)

    for email, role in desired.items():
        found = ws_roles.get(email)
        if found is None:
            stats["members_pending"] += 1
            continue
        user_id, ws_role = found
        if ws_role >= ADMIN_ROLE:
            # directors and admins see everything: they join a brand when they need to
            continue
        if _ensure_member(project, user_id, min(role, ws_role)):
            stats["members_added"] += 1
            changed = True

    if not members_authoritative:
        return changed

    service = get_service_user()
    desired_ids = {ws_roles[email][0] for email in desired if email in ws_roles}
    for membership in ProjectMember.objects.filter(project_id=project.id, is_active=True).select_related("member"):
        member = membership.member
        if member.is_bot or member.id == service.id or member.id in desired_ids:
            continue
        ws_role = next((r for uid, r in ws_roles.values() if uid == member.id), None)
        if ws_role is not None and ws_role >= ADMIN_ROLE:
            # a workspace admin who joined by themself (break glass): left alone, on record
            logger.info(
                "zil brand project %s: workspace admin %s is a member without being on the brand's team",
                project.id,
                member.email,
            )
            continue
        membership.is_active = False
        membership.save(update_fields=["is_active", "updated_at"])
        stats["members_removed"] += 1
        changed = True
    return changed


def _adoptable_project(workspace, name):
    """A live project of the workspace named like the brand and not Zil's yet, except the BU's own."""
    if name.strip().lower() == (workspace.name or "").strip().lower():
        return None
    return (
        Project.objects.filter(workspace_id=workspace.id, name__iexact=name, zil_brand__isnull=True)
        .order_by("created_at")
        .first()
    )


def _clean_adopted(project):
    """An adopted project becomes Zil's: nobody joins it by an old invitation, and the agents Plane
    put in it when it was made leave (on a brand they are added on request)."""
    ProjectMemberInvite.objects.filter(project_id=project.id, accepted=False).delete(soft=False)
    ProjectMember.objects.filter(
        project_id=project.id, is_active=True, member__is_bot=True, member__bot_type=BotTypeEnum.ZIL_AGENT
    ).update(is_active=False)


def _apply_brand(workspace, brand, mapping, owner, template, stats, ws_roles):
    """Create, adopt or update one brand's project. Returns (mapping, status)."""
    brand_id = brand["id"]
    name = brand_project_name(brand.get("name"))
    color = brand.get("color") if COLOR_RE.match(str(brand.get("color") or "")) else ""
    status = "unchanged"

    if mapping is None:
        project = _adoptable_project(workspace, name)
        if project is not None:
            status = "adopted"
            stats["adopted"] += 1
            auto_name = project.name
            _clean_adopted(project)
        else:
            status = "created"
            stats["created"] += 1
            auto_name = _unique_name(workspace.id, name, brand_id)
            project = create_zil_project(
                workspace, auto_name, allocate_identifier(workspace.id, auto_name), owner, color, template
            )
        mapping = ZilBrandProject(
            workspace_id=workspace.id,
            project=project,
            kind=ZilBrandProject.BRAND_KIND,
            zil_brand_id=brand_id,
            auto_name=auto_name,
            identifier=project.identifier,
        )
        mapping.save(disable_auto_set_user=True)

    project = mapping.project
    fields = set()

    new_name = _unique_name(workspace.id, name, brand_id, project.id)
    if new_name != mapping.auto_name and project.name == mapping.auto_name:
        project.name = new_name
        fields.add("name")
        stats["renamed"] += 1
    if project.name == new_name:
        mapping.auto_name = new_name

    # private on every run: nobody turns a brand's project public, not even for a while
    if project.network != ProjectNetwork.SECRET.value:
        project.network = ProjectNetwork.SECRET.value
        fields.add("network")
    logo_props = _logo_props(color)
    if (project.logo_props or {}).get("in_use") != "emoji" and project.logo_props != logo_props:
        project.logo_props = logo_props
        fields.add("logo_props")
    if fields:
        project.save(update_fields=[*fields, "updated_at"])

    if brand["status"] == ZilBrandProject.ACTIVE and project.archived_at is not None:
        _restore(project)
        stats["restored"] += 1
        fields.add("archived_at")

    brand_fields = {
        "logo_url": str(brand.get("logo") or "")[:2000],
        "color": color,
        "status": brand["status"],
    }
    if any(getattr(mapping, key) != value for key, value in brand_fields.items()):
        fields.add("brand")
    for key, value in brand_fields.items():
        setattr(mapping, key, value)

    members_changed = apply_members(mapping, brand.get("members"), brand["members_authoritative"], stats, ws_roles)
    now = timezone.now()
    mapping.synced_at = now
    mapping.members_synced_at = now
    mapping.save(disable_auto_set_user=True)

    if status == "unchanged" and (fields or members_changed):
        status = "updated"
    return mapping, status


def _parse_brands(brands):
    parsed = {}
    for brand in brands or []:
        if not isinstance(brand, dict):
            continue
        brand_id = str(brand.get("brandId") or "").strip().lower()
        if not is_valid_client_id(brand_id):
            continue
        status = str(brand.get("status") or "active").strip().lower()
        parsed[brand_id] = {
            **brand,
            "id": brand_id,
            "status": ZilBrandProject.ARCHIVED if status == ZilBrandProject.ARCHIVED else ZilBrandProject.ACTIVE,
            "members_authoritative": brand.get("membersAuthoritative") is True,
        }
    return parsed


class _DryRun(Exception):
    pass


def apply_brand_roster(
    workspace_id, brands, authoritative, computed_at=None, force=False, dry_run=False, template=None
):
    """Apply a workspace's brand roster. Returns the counters and one result per brand.

    `computed_at` (aware datetime): when Zil started computing it; a workspace that already applied
    a roster computed after it ignores this one (`stale`). With `dry_run` everything is computed
    and nothing is kept.
    """
    brands_by_id = _parse_brands(brands)
    stats = {
        "stale": False,
        "refused": None,
        "dry_run": bool(dry_run),
        "created": 0,
        "adopted": 0,
        "renamed": 0,
        "archived": 0,
        "restored": 0,
        "skipped": 0,
        "members_added": 0,
        "members_removed": 0,
        "members_pending": 0,
        "brands": [],
    }
    try:
        with transaction.atomic():
            _lock_workspace(workspace_id)
            _apply_roster(workspace_id, brands_by_id, authoritative, computed_at, force, template, stats)
            if dry_run:
                raise _DryRun()
    except _DryRun:
        pass
    return stats


def _apply_roster(workspace_id, brands_by_id, authoritative, computed_at, force, template, stats):
    roster = ZilBrandRoster.objects.filter(workspace_id=workspace_id).first()
    if roster is not None and _is_stale(computed_at, roster.synced_at):
        stats["stale"] = True
        return
    if authoritative and not brands_by_id:
        # a truncated payload, not "this BU works no brand": nothing is archived, nothing stamped
        stats["refused"] = "empty_roster"
        return

    workspace = Workspace.objects.get(pk=workspace_id)
    owner = get_service_user()
    ws_roles = _workspace_roles(workspace_id)
    mappings = {
        m.zil_brand_id: m
        for m in ZilBrandProject.objects.filter(
            workspace_id=workspace_id, kind=ZilBrandProject.BRAND_KIND
        ).select_related("project")
    }
    for brand_id, mapping in list(mappings.items()):
        if mapping.project.deleted_at is not None:
            # its project was deleted some other way: the brand gets a new one
            mapping.delete(soft=False)
            del mappings[brand_id]

    results = {}
    for brand_id, brand in brands_by_id.items():
        if brand_id not in mappings and brand["status"] == ZilBrandProject.ARCHIVED:
            # an archived brand that never had a project here does not get one: it would be born dead
            # (and a first run with many of them would trip the archive fuse and leave them alive)
            stats["skipped"] += 1
            results[brand_id] = {
                "brandId": brand_id,
                "projectId": None,
                "identifier": None,
                "status": "skipped",
                "error": None,
            }
            continue
        try:
            with transaction.atomic():
                mapping, status = _apply_brand(
                    workspace, brand, mappings.get(brand_id), owner, template, stats, ws_roles
                )
            mappings[brand_id] = mapping
            results[brand_id] = {
                "brandId": brand_id,
                "projectId": str(mapping.project_id),
                "identifier": mapping.identifier,
                "status": status,
                "error": None,
            }
        except Exception as e:  # one brand never stops the others (their revocations included)
            logger.exception("zil brand project %s failed in workspace %s", brand_id, workspace_id)
            mapping = mappings.get(brand_id)
            results[brand_id] = {
                "brandId": brand_id,
                "projectId": str(mapping.project_id) if mapping else None,
                "identifier": mapping.identifier if mapping else None,
                "status": "error",
                "error": str(e)[:300],
            }

    to_archive = []
    for brand_id, mapping in mappings.items():
        if mapping.project.archived_at is not None or results.get(brand_id, {}).get("status") == "error":
            continue
        leaving = brand_id not in brands_by_id and authoritative
        if leaving or brands_by_id.get(brand_id, {}).get("status") == ZilBrandProject.ARCHIVED:
            to_archive.append(brand_id)

    live = sum(1 for m in mappings.values() if m.project.archived_at is None)
    minimum, fraction = archive_fuse()
    if to_archive and not force and len(to_archive) > minimum and len(to_archive) > fraction * live:
        stats["refused"] = "archive_fuse"
        logger.warning(
            "zil brand roster for workspace %s would archive %s of %s brands: refused without force",
            workspace_id,
            len(to_archive),
            live,
        )
        to_archive = []

    for brand_id in to_archive:
        mapping = mappings[brand_id]
        _archive(mapping.project)
        if mapping.status != ZilBrandProject.ARCHIVED:
            mapping.status = ZilBrandProject.ARCHIVED
            mapping.save(update_fields=["status", "updated_at"])
        stats["archived"] += 1
        result = results.setdefault(
            brand_id,
            {
                "brandId": brand_id,
                "projectId": str(mapping.project_id),
                "identifier": mapping.identifier,
                "error": None,
            },
        )
        result["status"] = "archived"

    stats["brands"] = list(results.values())
    if roster is None:
        roster = ZilBrandRoster(workspace_id=workspace_id)
    roster.synced_at = computed_at or timezone.now()
    roster.save(disable_auto_set_user=True)


def apply_pending_brand_memberships(user):
    """On sign-in: join the brands Zil put this person on while they had never signed in to Ops."""
    email = (user.email or "").strip().lower()
    if not email or user.is_bot:
        return 0
    added = 0
    rows = ZilBrandMember.objects.filter(
        email=email, brand_project__deleted_at__isnull=True, brand_project__project__deleted_at__isnull=True
    ).select_related("brand_project__project")
    for row in rows:
        project = row.brand_project.project
        ws_role = (
            WorkspaceMember.objects.filter(workspace_id=project.workspace_id, member=user, is_active=True)
            .values_list("role", flat=True)
            .first()
        )
        if ws_role is None or ws_role >= ADMIN_ROLE:
            continue
        if _ensure_member(project, user.id, min(row.role, ws_role)):
            added += 1
    return added


def ensure_migration_project(workspace):
    """The workspace's private "Migración" project, for the pages of clients with several brands
    (sorted by hand into their brands). Its members are the workspace's directors and admins."""
    mapping = (
        ZilBrandProject.objects.filter(workspace_id=workspace.id, kind=ZilBrandProject.MIGRATION_KIND)
        .select_related("project")
        .first()
    )
    if mapping is not None and mapping.project.deleted_at is None:
        project = mapping.project
    else:
        owner = get_service_user()
        name = _unique_name(workspace.id, MIGRATION_PROJECT_NAME, "")
        project = create_zil_project(workspace, name, allocate_identifier(workspace.id, MIGRATION_IDENTIFIER), owner)
        mapping = ZilBrandProject(
            workspace_id=workspace.id,
            project=project,
            kind=ZilBrandProject.MIGRATION_KIND,
            auto_name=name,
            identifier=project.identifier,
        )
        mapping.save(disable_auto_set_user=True)
    for user_id in WorkspaceMember.objects.filter(
        workspace_id=workspace.id, is_active=True, role=ADMIN_ROLE, member__is_bot=False, member__is_active=True
    ).values_list("member_id", flat=True):
        _ensure_member(project, user_id, ADMIN_ROLE)
    return project


def apply_user_brand_projects(email, items, authoritative=False, user=None):
    """The fast path for one person (POST /sync/user `brand_projects`): Zil says which brands they
    work on right now, so a revoked assignment does not wait for the next roster.

    `items`: [{brandId, role, workspace_slug?}]; without `workspace_slug` an item covers the brand's
    project in every workspace. Adds always; with `authoritative`, the person also leaves every brand
    project not in the list (their wish on record included). Workspace admins are left alone, like in
    the roster. Returns counters.
    """
    email = (email or "").strip().lower()
    stats = {"added": 0, "removed": 0, "pending": 0}
    wanted = {}
    for item in items or []:
        if not isinstance(item, dict):
            continue
        brand_id = str(item.get("brandId") or "").strip().lower()
        if not is_valid_client_id(brand_id):
            continue
        role = BRAND_ROLES.get(str(item.get("role") or "member").strip().lower(), MEMBER_ROLE)
        slug = str(item.get("workspace_slug") or "").strip().lower() or None
        wanted[(brand_id, slug)] = max(role, wanted.get((brand_id, slug), 0))

    mappings = ZilBrandProject.objects.filter(
        kind=ZilBrandProject.BRAND_KIND, project__deleted_at__isnull=True
    ).select_related("project", "workspace")
    targets = {}
    for mapping in mappings.filter(zil_brand_id__in={brand_id for brand_id, _ in wanted}):
        role = wanted.get((mapping.zil_brand_id, mapping.workspace.slug)) or wanted.get((mapping.zil_brand_id, None))
        if role:
            targets[mapping.id] = (mapping, role)

    with transaction.atomic():
        for mapping, role in targets.values():
            row = ZilBrandMember.objects.filter(brand_project=mapping, email=email).first()
            if row is None:
                ZilBrandMember(brand_project=mapping, email=email, role=role).save(disable_auto_set_user=True)
            elif row.role != role:
                row.role = role
                row.save(update_fields=["role", "updated_at"])
            ws_role = (
                WorkspaceMember.objects.filter(workspace_id=mapping.workspace_id, member=user, is_active=True)
                .values_list("role", flat=True)
                .first()
                if user is not None
                else None
            )
            if ws_role is None:
                stats["pending"] += 1
            elif ws_role < ADMIN_ROLE and _ensure_member(mapping.project, user.id, min(role, ws_role)):
                stats["added"] += 1

        if not authoritative:
            return stats
        ZilBrandMember.objects.filter(email=email, brand_project__kind=ZilBrandProject.BRAND_KIND).exclude(
            brand_project_id__in=list(targets)
        ).delete(soft=False)
        if user is None:
            return stats
        admin_workspaces = set(
            WorkspaceMember.objects.filter(member=user, is_active=True, role__gte=ADMIN_ROLE).values_list(
                "workspace_id", flat=True
            )
        )
        keep = {mapping.project_id for mapping, _ in targets.values()}
        for membership in ProjectMember.objects.filter(
            member=user, is_active=True, project__zil_brand__kind=ZilBrandProject.BRAND_KIND
        ):
            if membership.project_id in keep or membership.workspace_id in admin_workspaces:
                continue
            membership.is_active = False
            membership.save(update_fields=["is_active", "updated_at"])
            stats["removed"] += 1
    return stats
