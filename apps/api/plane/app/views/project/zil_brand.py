# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""The brands (Marcas) a person works on, and a brand's live sheet from Zil Workspace."""

# Django imports
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.app.permissions import ROLE, allow_permission
from plane.db.models import ProjectMember, ZilBrandProject
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


OPS_PEOPLE = ("community_managers", "leaders")
OPS_LINKS = ("materials_links", "finals_links")
MAX_LINKS = 30
MAX_LINK_NAME = 120
validate_link = URLValidator(schemes=["http", "https"])


def serialize_brand_ops(mapping):
    """What Ops itself keeps on the brand: who runs it and where its Drive folders are.

    People show only while they are on the brand's team: someone Zil takes off the brand stops
    showing as its CM or líder (and shows again if they come back).
    """
    team = ProjectMember.objects.filter(project_id=mapping.project_id, is_active=True).values("member_id")

    def on_team(people):
        return [str(pk) for pk in people.filter(id__in=team).order_by("display_name").values_list("id", flat=True)]

    return {
        "community_manager_ids": on_team(mapping.community_managers),
        "leader_ids": on_team(mapping.leaders),
        "materials_links": mapping.materials_links,
        "finals_links": mapping.finals_links,
    }


def active_member_ids(project_id, member_ids):
    """The ids, as given, when every one is an active member of the project; None otherwise."""
    if not isinstance(member_ids, list) or not all(isinstance(pk, str) for pk in member_ids):
        return None
    member_ids = list(dict.fromkeys(member_ids))
    try:
        found = ProjectMember.objects.filter(project_id=project_id, member_id__in=member_ids, is_active=True).count()
    except (ValidationError, ValueError):
        return None
    return member_ids if found == len(member_ids) else None


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
    PATCH → change what Ops keeps on it: the CMs a cargo and líderes (active project members) and the
    Drive links of materiales and finales. Each field sent replaces the whole list.

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
            member_ids = active_member_ids(project_id, request.data.get(key) or [])
            if member_ids is None:
                errors[key] = "Must be active members of this project"
            else:
                people[field] = member_ids
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
        for field, member_ids in people.items():
            getattr(mapping, field).set(member_ids)
        if links:
            for field, cleaned in links.items():
                setattr(mapping, field, cleaned)
            mapping.save(update_fields=[*links, "updated_at", "updated_by"])
        return Response({"ops": serialize_brand_ops(mapping)}, status=status.HTTP_200_OK)
