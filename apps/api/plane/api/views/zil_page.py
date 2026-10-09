# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Project pages over the API-key API (/api/v1), for the Ops MCP server and the live server.

The app's page views already carry every page rule (private pages, guests, locks, archive, the
page tree), so these are the same views with API-key auth instead of the session. Two additions:
retrieve reports whether the caller can edit the page, and page content is never written as HTML
here: the collaborative document is the source of truth, so agents edit through the live server
(which stores the result through the description route below, like any editor session).
"""

# Django imports
from django.db.models import Q

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.api.middleware.api_authentication import APIKeyAuthentication
from plane.api.rate_limit import ApiKeyRateThrottle
from plane.api.views.base import BaseAPIView
from plane.app.permissions import ROLE
from plane.app.views.page.base import PagesDescriptionViewSet, PageViewSet
from plane.db.models import APIToken, Page, ProjectMember, Workspace

CONTENT_FIELDS = ("description_html", "description_binary", "description_json", "description")


def can_edit_page(page, user, project_id):
    if page.owned_by_id == user.id:
        return True
    if page.access == Page.PRIVATE_ACCESS:
        return False
    return ProjectMember.objects.filter(
        project_id=project_id,
        member=user,
        is_active=True,
        role__in=[ROLE.ADMIN.value, ROLE.MEMBER.value],
    ).exists()


class ApiKeyPageAuthMixin:
    authentication_classes = [APIKeyAuthentication]
    throttle_classes = [ApiKeyRateThrottle]


class ApiPageViewSet(ApiKeyPageAuthMixin, PageViewSet):
    def retrieve(self, request, slug, project_id, page_id=None):
        # an agent reading a page is not a visit: keep it out of the person's recents
        request._request.GET = request._request.GET.copy()
        request._request.GET["track_visit"] = "false"
        response = super().retrieve(request, slug, project_id, page_id=page_id)
        if response.status_code == status.HTTP_200_OK:
            page = Page.objects.get(pk=page_id)
            response.data["is_folder"] = page.is_folder
            response.data["can_edit"] = can_edit_page(page, request.user, project_id)
        return response

    def partial_update(self, request, slug, project_id, page_id):
        if any(field in request.data for field in CONTENT_FIELDS):
            return Response(
                {"error": "Page content is edited through the page editor (MCP edit_page), not as HTML."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return super().partial_update(request, slug, project_id, page_id)


class ApiPagesDescriptionViewSet(ApiKeyPageAuthMixin, PagesDescriptionViewSet):
    pass


class ApiPageSearchEndpoint(BaseAPIView):
    """Pages the caller can see across the workspace's projects, by title or content."""

    MAX_RESULTS = 50

    def get(self, request, slug):
        query = (request.GET.get("q") or "").strip()
        project_id = request.GET.get("project_id")
        include_archived = request.GET.get("archived", "false").lower() == "true"

        memberships = ProjectMember.objects.filter(
            workspace__slug=slug,
            member=request.user,
            is_active=True,
            project__archived_at__isnull=True,
        )
        if project_id:
            memberships = memberships.filter(project_id=project_id)
        member_roles = dict(memberships.values_list("project_id", "role"))
        guest_projects = {pid for pid, role in member_roles.items() if role == ROLE.GUEST.value}

        pages = (
            Page.objects.filter(
                workspace__slug=slug,
                projects__id__in=list(member_roles),
                project_pages__deleted_at__isnull=True,
            )
            .filter(Q(owned_by=request.user) | Q(access=Page.PUBLIC_ACCESS))
            .prefetch_related("projects")
            .distinct()
        )
        if not include_archived:
            pages = pages.filter(archived_at__isnull=True)
        if query:
            pages = pages.filter(Q(name__icontains=query) | Q(description_stripped__icontains=query))

        results = []
        for page in pages.order_by("-updated_at")[: self.MAX_RESULTS * 2]:
            project = next((p for p in page.projects.all() if p.id in member_roles), None)
            if project is None:
                continue
            # guests only see their own pages unless the project lets them see all features
            if (
                project.id in guest_projects
                and not project.guest_view_all_features
                and page.owned_by_id != request.user.id
            ):
                continue
            results.append(
                {
                    "id": str(page.id),
                    "name": page.name,
                    "project_id": str(project.id),
                    "project_name": project.name,
                    "parent_id": str(page.parent_id) if page.parent_id else None,
                    "is_folder": page.is_folder,
                    "archived_at": page.archived_at,
                    "updated_at": page.updated_at,
                    "snippet": snippet(page.description_stripped or "", query),
                }
            )
            if len(results) >= self.MAX_RESULTS:
                break
        return Response({"results": results}, status=status.HTTP_200_OK)


def snippet(text, query, radius=80):
    text = " ".join(text.split())
    if not text:
        return ""
    index = text.lower().find(query.lower()) if query else -1
    if index < 0:
        return text[: radius * 2] + ("…" if len(text) > radius * 2 else "")
    start = max(0, index - radius)
    end = min(len(text), index + len(query) + radius)
    return ("…" if start else "") + text[start:end] + ("…" if end < len(text) else "")


class ApiMcpWhoAmIEndpoint(BaseAPIView):
    """Who an API token belongs to and the workspace it was issued for (the MCP server's token check)."""

    def get(self, request):
        token = APIToken.objects.select_related("workspace").filter(token=request.auth).first()
        workspaces = (
            Workspace.objects.filter(
                workspace_member__member=request.user,
                workspace_member__is_active=True,
                workspace_member__deleted_at__isnull=True,
            )
            .distinct()
            .order_by("name")
        )
        return Response(
            {
                "user": {
                    "id": str(request.user.id),
                    "email": request.user.email,
                    "display_name": request.user.display_name,
                },
                "workspace_slug": token.workspace.slug if token and token.workspace else None,
                "workspaces": [{"slug": w.slug, "name": w.name} for w in workspaces],
            },
            status=status.HTTP_200_OK,
        )
