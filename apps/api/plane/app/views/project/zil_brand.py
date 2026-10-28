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


OPS_PEOPLE = ("community_manager", "leader")
OPS_LINKS = ("materials_url", "finals_url")
validate_link = URLValidator(schemes=["http", "https"])


def serialize_brand_ops(mapping):
    """What Ops itself keeps on the brand: who runs it and where its Drive folders are."""
    return {
        "community_manager_id": str(mapping.community_manager_id) if mapping.community_manager_id else None,
        "leader_id": str(mapping.leader_id) if mapping.leader_id else None,
        "materials_url": mapping.materials_url,
        "finals_url": mapping.finals_url,
    }


def is_active_member(project_id, member_id):
    try:
        return ProjectMember.objects.filter(project_id=project_id, member_id=member_id, is_active=True).exists()
    except (ValidationError, ValueError):
        return False


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
    PATCH → change what Ops keeps on it: CM a cargo, líder (active project members) and the Drive links.

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
        changed = []
        for field in OPS_PEOPLE:
            key = f"{field}_id"
            if key not in request.data:
                continue
            member_id = request.data.get(key) or None
            if member_id is not None and not is_active_member(project_id, member_id):
                errors[key] = "Must be an active member of this project"
                continue
            setattr(mapping, key, member_id)
            changed.append(field)
        for field in OPS_LINKS:
            if field not in request.data:
                continue
            link = (request.data.get(field) or "").strip()
            if link:
                try:
                    validate_link(link)
                except ValidationError:
                    errors[field] = "Must be an http(s) link"
                    continue
            setattr(mapping, field, link)
            changed.append(field)
        if errors:
            return Response(errors, status=status.HTTP_400_BAD_REQUEST)
        if changed:
            mapping.save(update_fields=[*changed, "updated_at", "updated_by"])
        return Response({"ops": serialize_brand_ops(mapping)}, status=status.HTTP_200_OK)
