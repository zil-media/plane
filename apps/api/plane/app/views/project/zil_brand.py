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
from plane.db.models import ProjectMember, ZilBrandClient, ZilBrandOps, ZilBrandProject, ZilBrandResponsible
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
        if "member_id" not in item:
            return None
        unit_id, member_id = item.get("workspace_id"), item["member_id"]
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


def serialize_portal(mapping, portal):
    """The "Portal del cliente" section of the Marca tab: on/off, its link and the client accounts."""
    from plane.utils.zil_client_portal import access_status, is_paused, portal_url

    clients = ZilBrandClient.objects.filter(brand_project=mapping).select_related("user").order_by("email")
    return {
        "enabled": bool(portal and portal.enabled),
        "paused": is_paused(mapping.project, mapping),
        "url": portal_url(str(mapping.project_id)),
        "folder_id": str(portal.pages_folder_id) if portal and portal.pages_folder_id else None,
        # rounds of changes per post and the hours to ask for them from its first review (0: no limit)
        "change_rounds": portal.change_rounds if portal else 2,
        "change_hours": portal.change_hours if portal else 72,
        "clients": [
            {
                "id": str(client.id),
                "email": client.email,
                "status": access_status(client),
                "has_account": client.user_id is not None,
                "invited_at": client.invited_at,
                "last_login": client.user.last_login_time if client.user_id else None,
            }
            for client in clients
        ],
    }


class ZilProjectPortalEndpoint(BaseAPIView):
    """The brand's client portal, from the Marca tab.

    GET → on/off, link, the "Cliente" folder and the client accounts (they come from Zil Workspace).
    PATCH {enabled?, change_rounds?, change_hours?} → turn it on (every client never invited gets the
    invitation) or off; the rounds of changes per post and the hours to ask for them (0: no limit).
    """

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def get(self, request, slug, project_id):
        from plane.db.models import ZilClientPortal

        mapping = brand_mapping(slug, project_id)
        if mapping is None:
            return Response({"error": "Not a brand project"}, status=status.HTTP_404_NOT_FOUND)
        portal = ZilClientPortal.objects.filter(project_id=project_id).first()
        return Response(serialize_portal(mapping, portal), status=status.HTTP_200_OK)

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def patch(self, request, slug, project_id):
        from plane.utils.zil_client_portal import invite_pending, seed_brand_content

        mapping = brand_mapping(slug, project_id)
        if mapping is None:
            return Response({"error": "Not a brand project"}, status=status.HTTP_404_NOT_FOUND)
        enabled = request.data.get("enabled")
        if enabled is not None and not isinstance(enabled, bool):
            return Response({"enabled": "Must be true or false"}, status=status.HTTP_400_BAD_REQUEST)
        limits = {}
        for field, top in (("change_rounds", 20), ("change_hours", 24 * 60)):
            if field in request.data:
                value = request.data.get(field)
                if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= top:
                    return Response({field: f"A whole number from 0 to {top}"}, status=status.HTTP_400_BAD_REQUEST)
                limits[field] = value
        if enabled is None and not limits:
            return Response({"enabled": "Nothing to change"}, status=status.HTTP_400_BAD_REQUEST)
        with transaction.atomic():
            portal = seed_brand_content(mapping.project, request.user)
            changed = [field for field, value in limits.items() if getattr(portal, field) != value]
            for field in changed:
                setattr(portal, field, limits[field])
            if enabled is not None and portal.enabled != enabled:
                portal.enabled = enabled
                changed.append("enabled")
            if changed:
                portal.save(update_fields=[*changed, "updated_at"])
        if enabled:
            invite_pending(portal)
        return Response(serialize_portal(mapping, portal), status=status.HTTP_200_OK)


class ZilProjectVideoAlertsEndpoint(BaseAPIView):
    """GET → {"issues": {issue_id: [{link_id, title, url}]}}: the work items whose Drive video the
    brand's clients can't open (Ops' calendar marks them; the client reads "being processed")."""

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST])
    def get(self, request, slug, project_id):
        from plane.db.models import IssueLink

        if brand_mapping(slug, project_id) is None:
            return Response({"issues": {}}, status=status.HTTP_200_OK)
        rows = IssueLink.objects.filter(
            project_id=project_id,
            metadata__zil_drive__status="broken",
            issue__deleted_at__isnull=True,
            issue__archived_at__isnull=True,
        ).values("id", "issue_id", "title", "url")[:500]
        issues = {}
        for row in rows:
            issues.setdefault(str(row["issue_id"]), []).append(
                {"link_id": str(row["id"]), "title": row["title"] or row["url"], "url": row["url"]}
            )
        return Response({"issues": issues}, status=status.HTTP_200_OK)


class ZilProjectPortalInviteEndpoint(BaseAPIView):
    """POST → send a client a new invitation link (the previous one stops working)."""

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def post(self, request, slug, project_id, client_id):
        from plane.db.models import ZilClientPortal
        from plane.utils.zil_client_portal import invite_client

        mapping = brand_mapping(slug, project_id)
        if mapping is None:
            return Response({"error": "Not a brand project"}, status=status.HTTP_404_NOT_FOUND)
        client = ZilBrandClient.objects.filter(brand_project=mapping, pk=client_id).first()
        if client is None:
            return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)
        if not invite_client(client):
            return Response(
                {"error": "The portal is off or paused, or the client has no account"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        portal = ZilClientPortal.objects.filter(project_id=project_id).first()
        return Response(serialize_portal(mapping, portal), status=status.HTTP_200_OK)


def serialize_page_comment(comment):
    """A page comment in the shape Ops' comment components read (TIssueComment), always external."""
    actor = comment.actor
    return {
        "id": str(comment.id),
        "workspace": str(comment.workspace_id),
        "project": str(comment.project_id),
        "issue": str(comment.page_id),
        "actor": str(comment.actor_id),
        "actor_detail": {
            "id": str(actor.id),
            "display_name": actor.display_name,
            "first_name": actor.first_name,
            "last_name": actor.last_name,
            "avatar_url": actor.avatar_url,
            "is_bot": actor.is_bot,
        },
        "comment_html": comment.comment_html,
        "comment_stripped": comment.comment_stripped,
        "created_at": comment.created_at,
        "updated_at": comment.updated_at,
        "edited_at": comment.edited_at,
        "created_by": str(comment.created_by_id) if comment.created_by_id else None,
        "access": "EXTERNAL",
        "attachments": [],
        "comment_reactions": [],
    }


def client_folder_page(slug, project_id, page_id):
    """The page when it is inside its brand project's "Cliente" folder, else None."""
    from plane.db.models import Page
    from plane.utils.zil_client_portal import is_in_client_folder

    page = Page.objects.filter(
        pk=page_id,
        workspace__slug=slug,
        project_pages__project_id=project_id,
        project_pages__deleted_at__isnull=True,
    ).first()
    return page if page is not None and is_in_client_folder(page) else None


class ZilPageClientCommentsEndpoint(BaseAPIView):
    """The conversation with the brand's clients on a page of the "Cliente" folder (the client sees it
    in the portal). GET → the comments. POST {comment_html} → the team's answer (the client gets an
    email). PATCH / DELETE on one → only its author."""

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST])
    def get(self, request, slug, project_id, page_id):
        from plane.db.models import ZilPageComment

        page = client_folder_page(slug, project_id, page_id)
        if page is None:
            return Response({"error": "Not a page of the client folder"}, status=status.HTTP_404_NOT_FOUND)
        comments = ZilPageComment.objects.filter(page=page).select_related("actor").order_by("created_at")
        return Response([serialize_page_comment(c) for c in comments], status=status.HTTP_200_OK)

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def post(self, request, slug, project_id, page_id):
        from plane.db.models import ZilPageComment
        from plane.utils.content_validator import validate_html_content
        from plane.utils.zil_client_portal import notify_page_comment

        page = client_folder_page(slug, project_id, page_id)
        if page is None:
            return Response({"error": "Not a page of the client folder"}, status=status.HTTP_404_NOT_FOUND)
        html = str(request.data.get("comment_html") or "").strip()
        is_valid, error, sanitized = validate_html_content(html)
        if not is_valid or not html or html == "<p></p>":
            return Response({"comment_html": error or "Write a comment"}, status=status.HTTP_400_BAD_REQUEST)
        comment = ZilPageComment(
            page=page,
            project_id=project_id,
            workspace_id=page.workspace_id,
            actor=request.user,
            comment_html=sanitized or html,
        )
        comment.save(created_by_id=request.user.id)
        transaction.on_commit(lambda: notify_page_comment(page, comment, request.user))
        return Response(serialize_page_comment(comment), status=status.HTTP_201_CREATED)


class ZilPageClientCommentDetailEndpoint(BaseAPIView):
    """PATCH {comment_html} / DELETE one comment of the client conversation: only its author."""

    def _comment(self, request, slug, project_id, page_id, pk):
        from plane.db.models import ZilPageComment

        if client_folder_page(slug, project_id, page_id) is None:
            return None
        return ZilPageComment.objects.filter(pk=pk, page_id=page_id, actor=request.user).first()

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def patch(self, request, slug, project_id, page_id, pk):
        from django.utils import timezone

        from plane.utils.content_validator import validate_html_content

        comment = self._comment(request, slug, project_id, page_id, pk)
        if comment is None:
            return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)
        html = str(request.data.get("comment_html") or "").strip()
        is_valid, error, sanitized = validate_html_content(html)
        if not is_valid or not html:
            return Response({"comment_html": error or "Write a comment"}, status=status.HTTP_400_BAD_REQUEST)
        comment.comment_html = sanitized or html
        comment.edited_at = timezone.now()
        comment.save(update_fields=["comment_html", "comment_stripped", "edited_at", "updated_at"])
        return Response(serialize_page_comment(comment), status=status.HTTP_200_OK)

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def delete(self, request, slug, project_id, page_id, pk):
        comment = self._comment(request, slug, project_id, page_id, pk)
        if comment is None:
            return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)
        comment.delete(soft=False)
        return Response(status=status.HTTP_204_NO_CONTENT)
