# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Django imports
from django.db import IntegrityError, transaction

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.app.permissions import allow_permission, ROLE
from plane.db.models import Page, PageZilClientLink
from plane.utils.zil_client import (
    ZilUnavailable,
    apply_zil_client_fields,
    get_zil_client,
    is_valid_client_id,
    search_zil_clients,
    zil_enabled,
)
from ..base import BaseAPIView


def serialize_link(link):
    return {
        "id": link.zil_client_id,
        "alias": link.alias,
        "company_name": link.company_name,
        "lifecycle_status": link.lifecycle_status,
        "business_unit_slug": link.business_unit_slug,
        "synced_at": link.synced_at,
    }


class ZilClientSearchEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def get(self, request, slug, project_id):
        if not zil_enabled():
            return Response({"enabled": False, "results": []}, status=status.HTTP_200_OK)

        q = request.GET.get("q", "").strip()[:100]
        try:
            results = search_zil_clients(slug, q)
        except ZilUnavailable:
            return Response(
                {"enabled": True, "error": "ZIL_UNAVAILABLE"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        linked = dict(
            PageZilClientLink.objects.filter(
                project_id=project_id, zil_client_id__in=[c.get("id") for c in results]
            ).values_list("zil_client_id", "page_id")
        )
        for client in results:
            client["linkedPageId"] = linked.get(client.get("id"))

        return Response({"enabled": True, "results": results}, status=status.HTTP_200_OK)


class PageZilClientLinkEndpoint(BaseAPIView):
    def _get_folder(self, request, slug, project_id, page_id):
        page = Page.objects.filter(
            pk=page_id,
            workspace__slug=slug,
            projects__id=project_id,
            project_pages__deleted_at__isnull=True,
        ).first()
        if page is None or (page.access == Page.PRIVATE_ACCESS and page.owned_by_id != request.user.id):
            return None, Response({"error": "Page not found"}, status=status.HTTP_404_NOT_FOUND)
        if not page.is_folder:
            return None, Response(
                {"error": "Only folders can be linked to a client", "error_message": "PAGE_NOT_FOLDER"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if page.archived_at is not None:
            return None, Response(
                {"error": "Page is archived", "error_message": "PAGE_ARCHIVED"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return page, None

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def post(self, request, slug, project_id, page_id):
        if not zil_enabled():
            return Response({"error": "ZIL_DISABLED"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        page, error_response = self._get_folder(request, slug, project_id, page_id)
        if error_response:
            return error_response

        client_id = str(request.data.get("zil_client_id", "")).strip().lower()
        if not is_valid_client_id(client_id):
            return Response({"error": "Invalid client id"}, status=status.HTTP_400_BAD_REQUEST)

        # never trust display fields from the browser: re-read the client from Zil,
        # which also checks it belongs to one of this workspace's Business Units
        try:
            client = get_zil_client(slug, client_id)
        except ZilUnavailable:
            return Response({"error": "ZIL_UNAVAILABLE"}, status=status.HTTP_502_BAD_GATEWAY)
        if client is None:
            return Response(
                {"error": "Client not found for this workspace", "error_message": "ZIL_CLIENT_NOT_FOUND"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        existing = (
            PageZilClientLink.objects.filter(project_id=project_id, zil_client_id=client_id)
            .exclude(page_id=page.id)
            .first()
        )
        if existing:
            return Response(
                {"error": "ZIL_CLIENT_ALREADY_LINKED", "page_id": existing.page_id},
                status=status.HTTP_409_CONFLICT,
            )

        try:
            with transaction.atomic():
                # a folder holds one link: replace any previous one
                PageZilClientLink.all_objects.filter(page_id=page.id).delete()
                link = PageZilClientLink(
                    workspace_id=page.workspace_id,
                    project_id=project_id,
                    page_id=page.id,
                    zil_client_id=client_id,
                    created_by=request.user,
                    updated_by=request.user,
                )
                apply_zil_client_fields(link, client)
                link.save()
        except IntegrityError:
            existing = PageZilClientLink.objects.filter(project_id=project_id, zil_client_id=client_id).first()
            return Response(
                {"error": "ZIL_CLIENT_ALREADY_LINKED", "page_id": existing.page_id if existing else None},
                status=status.HTTP_409_CONFLICT,
            )

        return Response(serialize_link(link), status=status.HTTP_200_OK)

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def delete(self, request, slug, project_id, page_id):
        page = Page.objects.filter(
            pk=page_id,
            workspace__slug=slug,
            projects__id=project_id,
            project_pages__deleted_at__isnull=True,
        ).first()
        if page is None or (page.access == Page.PRIVATE_ACCESS and page.owned_by_id != request.user.id):
            return Response({"error": "Page not found"}, status=status.HTTP_404_NOT_FOUND)

        PageZilClientLink.all_objects.filter(page_id=page.id).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
