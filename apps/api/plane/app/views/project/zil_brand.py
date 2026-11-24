# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""The brands (Marcas) a person works on, and a brand's live sheet from Zil Workspace."""

# Django imports
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import transaction

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.app.permissions import ROLE, allow_permission
from plane.db.models import ProjectMember, ZilBrandOps, ZilBrandProject, ZilBrandResponsible
from plane.utils.zil_client import ZilUnavailable, get_zil_brand, zil_enabled
from ..base import BaseAPIView

# what the sheet may carry, field by field: anything else Zil sends is dropped, so the client's
# legal data never reaches Ops even if Workspace sent it by mistake
BRAND_FIELDS = ("id", "name", "logoUrl", "color", "status")
SPEC_FIELDS = ("key", "label", "value", "hint")
LIST_FIELDS = {
    "assets": ("id", "type", "name", "url"),
    "files": ("id", "name", "type", "url"),
    "team": ("name", "email", "role"),
    "calls": ("id", "title", "date", "purpose", "summary", "url"),
    "projects": ("workspaceSlug", "businessUnit"),
}


def _pick(row, fields):
    return {key: row.get(key) for key in fields} if isinstance(row, dict) else None


def _rows(rows, fields):
    if not isinstance(rows, list):
        return []
    return [picked for picked in (_pick(row, fields) for row in rows) if picked]


def whitelist_sheet(body):
    """The brand sheet as Ops shows it, rebuilt from the allowed fields only."""
    specs = body.get("specs")
    sheet = {key: _rows(body.get(key), fields) for key, fields in LIST_FIELDS.items()}
    sheet["specs"] = (
        {"strip": _rows(specs.get("strip"), SPEC_FIELDS)[:3], "items": _rows(specs.get("items"), SPEC_FIELDS)}
        if isinstance(specs, dict)
        else None
    )
    sheet["brand"] = _pick(body.get("brand") or {}, BRAND_FIELDS)
    return sheet


def serialize_brand_project(mapping):
    project = mapping.project
    return {
        "project_id": str(project.id),
        "identifier": project.identifier,
        "name": project.name,
        "brand_id": mapping.zil_brand_id,
        "logo_url": mapping.logo_url,
        "color": mapping.color,
        "status": mapping.status,
        "archived": project.archived_at is not None,
        "kind": mapping.kind,
    }


OPS_PEOPLE = ("community_managers",)
OPS_LINKS = ("materials_links", "finals_links")
MAX_LINKS = 30
MAX_LINK_NAME = 120
validate_link = URLValidator(schemes=["http", "https"])


def brand_team(zil_brand_id):
    """The active memberships of everyone on the brand, in every workspace that works it.

    A brand worked by several Business Units has one project per workspace: its team is all of
    them, so a Meraki CM shows on the brand in Zil's workspace too.
    """
    return ProjectMember.objects.filter(
        project__zil_brand__zil_brand_id=zil_brand_id,
        project__zil_brand__kind=ZilBrandProject.BRAND_KIND,
        project__zil_brand__deleted_at__isnull=True,
        project__deleted_at__isnull=True,
        # a unit that stopped working the brand (its project archived) or a removed workspace is off it
        project__archived_at__isnull=True,
        workspace__deleted_at__isnull=True,
        is_active=True,
        member__is_bot=False,
        member__is_active=True,
    )


def brand_ops(mapping):
    """The brand's shared row (unsaved and empty while nobody loaded anything)."""
    found = ZilBrandOps.objects.filter(zil_brand_id=mapping.zil_brand_id).first()
    return found or ZilBrandOps(zil_brand_id=mapping.zil_brand_id)


def brand_units(zil_brand_id):
    """The live projects of the brand, one per Business Unit (workspace) that works it, by unit name."""
    return (
        ZilBrandProject.objects.filter(
            zil_brand_id=zil_brand_id,
            kind=ZilBrandProject.BRAND_KIND,
            project__deleted_at__isnull=True,
            project__archived_at__isnull=True,
            workspace__deleted_at__isnull=True,
        )
        .select_related("workspace")
        .order_by("workspace__name")
    )


def serialize_brand_ops(mapping, ops=None):
    """What Ops itself keeps on the brand: who runs it and where its Drive folders are, plus its team.

    People show only while they are on the brand's team: someone Zil takes off the brand (in every
    workspace) stops showing as its CM, and shows again if they come back. A unit's Responsable
    shows only while they work the brand in that unit.
    """
    ops = ops or brand_ops(mapping)
    team = {}
    for membership in brand_team(mapping.zil_brand_id).select_related("member", "member__avatar_asset", "workspace"):
        user = membership.member
        person = team.setdefault(
            str(user.id),
            {
                "id": str(user.id),
                "display_name": user.display_name or user.first_name or user.email,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "email": user.email,
                "avatar_url": user.avatar_url or "",
                "business_units": [],
                "business_unit_ids": [],
            },
        )
        if str(membership.workspace_id) not in person["business_unit_ids"]:
            person["business_unit_ids"].append(str(membership.workspace_id))
            person["business_units"].append(membership.workspace.name)

    def on_team(people):
        if ops.pk is None:
            return []
        return [str(pk) for pk in people.filter(id__in=team).order_by("display_name").values_list("id", flat=True)]

    chosen = {
        str(row.workspace_id): str(row.member_id)
        for row in ZilBrandResponsible.objects.filter(zil_brand_id=mapping.zil_brand_id)
    }
    responsibles = []
    for unit in brand_units(mapping.zil_brand_id):
        unit_id = str(unit.workspace_id)
        member_id = chosen.get(unit_id)
        on_unit = member_id in team and unit_id in team[member_id]["business_unit_ids"] if member_id else False
        responsibles.append(
            {"workspace_id": unit_id, "business_unit": unit.workspace.name, "member_id": member_id if on_unit else None}
        )

    return {
        "community_manager_ids": on_team(ops.community_managers),
        "responsibles": responsibles,
        "materials_links": ops.materials_links,
        "finals_links": ops.finals_links,
        "team": sorted(team.values(), key=lambda person: person["display_name"].lower()),
    }


def team_member_ids(zil_brand_id, member_ids):
    """The ids, as given, when every one is on the brand's team (in any workspace); None otherwise."""
    if not isinstance(member_ids, list) or not all(isinstance(pk, str) for pk in member_ids):
        return None
    member_ids = list(dict.fromkeys(member_ids))
    try:
        found = brand_team(zil_brand_id).filter(member_id__in=member_ids).values("member_id").distinct().count()
    except (ValidationError, ValueError):
        return None
    return member_ids if found == len(member_ids) else None


def clean_responsibles(zil_brand_id, items):
    """{workspace_id: member_id | None} when every item names a unit of the brand and someone who
    works the brand in that unit (None clears it); None when anything is off."""
    if not isinstance(items, list):
        return None
    units = {str(pk) for pk in brand_units(zil_brand_id).values_list("workspace_id", flat=True)}
    cleaned = {}
    for item in items:
        if not isinstance(item, dict):
            return None
        unit_id, member_id = item.get("workspace_id"), item.get("member_id")
        if unit_id not in units or not (member_id is None or isinstance(member_id, str)):
            return None
        if member_id is not None:
            try:
                on_unit = brand_team(zil_brand_id).filter(workspace_id=unit_id, member_id=member_id).exists()
            except (ValidationError, ValueError):
                return None
            if not on_unit:
                return None
        cleaned[unit_id] = member_id
    return cleaned


def clean_links(links):
    """[{name, url}] with names trimmed and every url an http(s) link; None when anything is off."""
    if not isinstance(links, list) or len(links) > MAX_LINKS:
        return None
    cleaned = []
    for link in links:
        if not isinstance(link, dict):
            return None
        url = str(link.get("url") or "").strip()
        name = str(link.get("name") or "").strip()[:MAX_LINK_NAME]
        try:
            validate_link(url)
        except ValidationError:
            return None
        cleaned.append({"name": name, "url": url})
    return cleaned


def brand_mapping(slug, project_id):
    return (
        ZilBrandProject.objects.filter(workspace__slug=slug, project_id=project_id, kind=ZilBrandProject.BRAND_KIND)
        .select_related("project")
        .first()
    )


class ZilMyBrandsEndpoint(BaseAPIView):
    """GET → the Zil projects of the workspace the person is an active member of ("Mis marcas")."""

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST], level="WORKSPACE")
    def get(self, request, slug):
        mappings = (
            ZilBrandProject.objects.filter(
                workspace__slug=slug,
                project__deleted_at__isnull=True,
                project__project_projectmember__member=request.user,
                project__project_projectmember__is_active=True,
                project__project_projectmember__deleted_at__isnull=True,
            )
            .select_related("project")
            .distinct()
            .order_by("project__name")
        )
        return Response([serialize_brand_project(m) for m in mappings], status=status.HTTP_200_OK)


class ZilProjectBrandEndpoint(BaseAPIView):
    """GET → the project's brand, what Ops keeps on it and its live sheet from Zil Workspace (the "Marca" tab).
    PATCH → change what Ops keeps on it: the CMs a cargo (on the brand's team, in any workspace),
    the Responsable of each unit (`responsibles: [{workspace_id, member_id | null}]`, someone who
    works the brand in that unit; units left out keep theirs) and the Drive links of materiales and
    finales. Each other field sent replaces the whole list. It is the brand's, so every workspace
    that works the brand sees the change.

    404 when the project is not a brand's. When Zil is off or down the brand comes back with
    `sheet: null` and `unavailable: true`, so the tab still shows the brand.
    """

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST])
    def get(self, request, slug, project_id):
        mapping = brand_mapping(slug, project_id)
        if mapping is None:
            return Response({"error": "Not a brand project"}, status=status.HTTP_404_NOT_FOUND)
        data = {
            "brand": serialize_brand_project(mapping),
            "ops": serialize_brand_ops(mapping),
            "sheet": None,
            "unavailable": False,
        }
        if not zil_enabled():
            data["unavailable"] = True
            return Response(data, status=status.HTTP_200_OK)
        try:
            body = get_zil_brand(slug, mapping.zil_brand_id, request.user.email)
        except ZilUnavailable:
            data["unavailable"] = True
            return Response(data, status=status.HTTP_200_OK)
        if body is not None:
            data["sheet"] = whitelist_sheet(body)
        return Response(data, status=status.HTTP_200_OK)

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def patch(self, request, slug, project_id):
        mapping = brand_mapping(slug, project_id)
        if mapping is None:
            return Response({"error": "Not a brand project"}, status=status.HTTP_404_NOT_FOUND)
        errors = {}
        people = {}
        for field in OPS_PEOPLE:
            key = f"{field[:-1]}_ids"
            if key not in request.data:
                continue
            member_ids = team_member_ids(mapping.zil_brand_id, request.data.get(key) or [])
            if member_ids is None:
                errors[key] = "Must be on the brand's team"
            else:
                people[field] = member_ids
        responsibles = None
        if "responsibles" in request.data:
            responsibles = clean_responsibles(mapping.zil_brand_id, request.data.get("responsibles") or [])
            if responsibles is None:
                errors["responsibles"] = "Each must be a unit of the brand and someone who works it there"
        links = {}
        for field in OPS_LINKS:
            if field not in request.data:
                continue
            cleaned = clean_links(request.data.get(field) or [])
            if cleaned is None:
                errors[field] = f"Must be at most {MAX_LINKS} http(s) links"
            else:
                links[field] = cleaned
        if errors:
            return Response(errors, status=status.HTTP_400_BAD_REQUEST)
        with transaction.atomic():
            ops, _ = ZilBrandOps.objects.select_for_update().get_or_create(zil_brand_id=mapping.zil_brand_id)
            for field, member_ids in people.items():
                getattr(ops, field).set(member_ids)
            for field, cleaned in links.items():
                setattr(ops, field, cleaned)
            ops.save(update_fields=[*links, "updated_at", "updated_by"])
            for unit_id, member_id in (responsibles or {}).items():
                if member_id is None:
                    ZilBrandResponsible.objects.filter(zil_brand_id=mapping.zil_brand_id, workspace_id=unit_id).delete(
                        soft=False
                    )
                else:
                    ZilBrandResponsible.objects.update_or_create(
                        zil_brand_id=mapping.zil_brand_id, workspace_id=unit_id, defaults={"member_id": member_id}
                    )
        return Response({"ops": serialize_brand_ops(mapping, ops)}, status=status.HTTP_200_OK)
