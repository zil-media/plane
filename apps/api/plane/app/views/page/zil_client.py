# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Django imports
from django.db import IntegrityError, transaction
from django.http import HttpResponseRedirect

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.app.permissions import allow_permission, ROLE
from plane.db.models import Page, PageZilClientLink, ZilClientsRoot
from plane.middleware.request_body_size import BRAND_FILE_MAX_BYTES
from plane.utils.zil_client import (
    ZilUnavailable,
    apply_zil_client_fields,
    get_zil_client,
    is_valid_client_id,
    search_zil_clients,
    zil_client_relay,
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
            # Zil narrows the list to the clients this person may pick
            results = search_zil_clients(slug, q, actor_email=request.user.email)
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
        # the folder that holds the clients' folders is no client's: linked, the sync would take it
        # for that client's folder and never create the real one
        if ZilClientsRoot.objects.filter(page_id=page.id).exists():
            return None, Response(
                {"error": "The clients folder cannot be linked to a client", "error_message": "PAGE_IS_CLIENTS_ROOT"},
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


ZIL_RELAY_ERRORS = {400, 403, 404, 409, 413}


class ZilClientRelayBase(BaseAPIView):
    """A linked client folder relays its client profile calls to Zil, as the requesting user."""

    def _linked_folder(self, request, slug, project_id, page_id):
        if not zil_enabled():
            return None, Response({"error": "ZIL_DISABLED"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        page = (
            Page.objects.filter(
                pk=page_id,
                workspace__slug=slug,
                projects__id=project_id,
                project_pages__deleted_at__isnull=True,
                kind=Page.FOLDER_KIND,
            )
            .select_related("zil_client_link")
            .first()
        )
        if page is None or (page.access == Page.PRIVATE_ACCESS and page.owned_by_id != request.user.id):
            return None, Response({"error": "Page not found"}, status=status.HTTP_404_NOT_FOUND)
        link = PageZilClientLink.objects.filter(page_id=page.id).first()
        if link is None:
            return None, Response(
                {"error": "This folder is not linked to a client", "error_message": "ZIL_CLIENT_NOT_LINKED"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return link, None

    def _relay(self, request, slug, link, method, subpath, json=None, files=None, ok_status=status.HTTP_200_OK):
        try:
            code, body = zil_client_relay(
                method, link.zil_client_id, subpath, slug, request.user.email, json=json, files=files
            )
        except ZilUnavailable:
            return None, Response({"error": "ZIL_UNAVAILABLE"}, status=status.HTTP_502_BAD_GATEWAY)
        if code in ZIL_RELAY_ERRORS:
            return None, Response({"error": body.get("message") or "ZIL_ERROR"}, status=code)
        if code >= 300:
            return None, Response({"error": "ZIL_UNAVAILABLE"}, status=status.HTTP_502_BAD_GATEWAY)
        return body, None


class PageZilClientProfileEndpoint(ZilClientRelayBase):
    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def get(self, request, slug, project_id, page_id):
        link, error = self._linked_folder(request, slug, project_id, page_id)
        if error:
            return error
        body, error = self._relay(request, slug, link, "GET", "/profile")
        if error:
            return error
        profile = body.get("profile") or {}
        # the profile is fresh: keep the folder's cached display fields in step
        apply_zil_client_fields(
            link,
            {
                "alias": profile.get("info", {}).get("alias"),
                "companyName": profile.get("info", {}).get("companyName"),
                "lifecycleStatus": profile.get("info", {}).get("lifecycleStatus"),
                "businessUnitSlug": (profile.get("info", {}).get("businessUnit") or {}).get("slug"),
            },
        )
        link.save(
            update_fields=["alias", "company_name", "lifecycle_status", "business_unit_slug", "synced_at", "updated_at"]
        )
        return Response(profile, status=status.HTTP_200_OK)


ASSET_FIELDS = ("kind", "label", "url", "externalId", "notes")


class PageZilClientAssetsEndpoint(ZilClientRelayBase):
    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def post(self, request, slug, project_id, page_id):
        link, error = self._linked_folder(request, slug, project_id, page_id)
        if error:
            return error
        data = {k: request.data[k] for k in ASSET_FIELDS if k in request.data}
        body, error = self._relay(request, slug, link, "POST", "/assets", json=data)
        if error:
            return error
        return Response(body.get("asset"), status=status.HTTP_201_CREATED)


class PageZilClientAssetDetailEndpoint(ZilClientRelayBase):
    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def patch(self, request, slug, project_id, page_id, asset_id):
        if not is_valid_client_id(asset_id):
            return Response({"error": "Invalid asset id"}, status=status.HTTP_400_BAD_REQUEST)
        link, error = self._linked_folder(request, slug, project_id, page_id)
        if error:
            return error
        data = {k: request.data[k] for k in ASSET_FIELDS if k in request.data and k != "kind"}
        body, error = self._relay(request, slug, link, "PATCH", f"/assets/{asset_id}", json=data)
        if error:
            return error
        return Response(body.get("asset"), status=status.HTTP_200_OK)

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def delete(self, request, slug, project_id, page_id, asset_id):
        if not is_valid_client_id(asset_id):
            return Response({"error": "Invalid asset id"}, status=status.HTTP_400_BAD_REQUEST)
        link, error = self._linked_folder(request, slug, project_id, page_id)
        if error:
            return error
        _, error = self._relay(request, slug, link, "DELETE", f"/assets/{asset_id}")
        if error:
            return error
        return Response(status=status.HTTP_204_NO_CONTENT)


class PageZilClientDriveEndpoint(ZilClientRelayBase):
    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def get(self, request, slug, project_id, page_id, asset_id):
        if not is_valid_client_id(asset_id):
            return Response({"error": "Invalid asset id"}, status=status.HTTP_400_BAD_REQUEST)
        link, error = self._linked_folder(request, slug, project_id, page_id)
        if error:
            return error
        body, error = self._relay(request, slug, link, "GET", f"/assets/{asset_id}/drive")
        if error:
            return error
        return Response(body.get("drive"), status=status.HTTP_200_OK)


class PageZilClientBrandFilesEndpoint(ZilClientRelayBase):
    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def post(self, request, slug, project_id, page_id):
        upload = request.FILES.get("file")
        if upload is None:
            return Response({"error": "Missing file"}, status=status.HTTP_400_BAD_REQUEST)
        if upload.size > BRAND_FILE_MAX_BYTES:
            return Response(
                {"error": "El archivo no puede pesar más de 20 MB."},
                status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )
        link, error = self._linked_folder(request, slug, project_id, page_id)
        if error:
            return error
        files = {"file": (upload.name, upload.read(), upload.content_type or "application/octet-stream")}
        body, error = self._relay(request, slug, link, "POST", "/brand-files", files=files)
        if error:
            return error
        return Response(body.get("file"), status=status.HTTP_201_CREATED)


class PageZilClientBrandFileEndpoint(ZilClientRelayBase):
    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def get(self, request, slug, project_id, page_id, file_id):
        """Open a brand file: Zil signs a 5-minute URL for its storage and the browser is sent there."""
        if not is_valid_client_id(file_id):
            return Response({"error": "Invalid file id"}, status=status.HTTP_400_BAD_REQUEST)
        link, error = self._linked_folder(request, slug, project_id, page_id)
        if error:
            return error
        body, error = self._relay(request, slug, link, "GET", f"/brand-files/{file_id}/url")
        if error:
            return error
        url = body.get("url")
        if not url:
            return Response({"error": "ZIL_UNAVAILABLE"}, status=status.HTTP_502_BAD_GATEWAY)
        return HttpResponseRedirect(url)

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def delete(self, request, slug, project_id, page_id, file_id):
        if not is_valid_client_id(file_id):
            return Response({"error": "Invalid file id"}, status=status.HTTP_400_BAD_REQUEST)
        link, error = self._linked_folder(request, slug, project_id, page_id)
        if error:
            return error
        _, error = self._relay(request, slug, link, "DELETE", f"/brand-files/{file_id}")
        if error:
            return error
        return Response(status=status.HTTP_204_NO_CONTENT)
