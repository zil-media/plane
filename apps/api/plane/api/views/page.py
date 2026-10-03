# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
import json

# Django imports
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.api.serializers import PageDetailSerializer, PageSerializer, PageUpdateSerializer
from plane.app.permissions import ROLE, ProjectPagePermission
from plane.app.serializers import PageBinaryUpdateSerializer
from plane.app.serializers import PageSerializer as AppPageSerializer
from plane.bgtasks.page_transaction_task import page_transaction
from plane.bgtasks.page_version_task import track_page_version
from plane.db.models import Page, Project, ProjectMember, UserFavorite
from plane.utils.error_codes import ERROR_CODES
from plane.utils.page_content import LiveServerUnavailable, apply_page_content
from plane.utils.page_tree import PageTreeError, set_archived_at_for_page_and_descendants, validate_new_parent
from .base import BaseAPIView


def page_error(code, message=None, http_status=status.HTTP_400_BAD_REQUEST):
    return Response({"error_code": ERROR_CODES[code], "error": message or code}, status=http_status)


class PageQuerysetMixin:
    """Pages of the project the requesting user can see — same rules as the app."""

    def get_queryset(self):
        slug = self.kwargs.get("slug")
        project_id = self.kwargs.get("project_id")
        queryset = (
            Page.objects.filter(
                workspace__slug=slug,
                projects__id=project_id,
                project_pages__deleted_at__isnull=True,
                projects__archived_at__isnull=True,
                projects__project_projectmember__member=self.request.user,
                projects__project_projectmember__is_active=True,
            )
            .filter(Q(owned_by=self.request.user) | Q(access=Page.PUBLIC_ACCESS))
            .distinct()
        )
        # guests only see their own pages unless the project opens everything to them
        is_guest = ProjectMember.objects.filter(
            workspace__slug=slug,
            project_id=project_id,
            member=self.request.user,
            role=ROLE.GUEST.value,
            is_active=True,
        ).exists()
        if is_guest and not Project.objects.filter(pk=project_id, guest_view_all_features=True).exists():
            queryset = queryset.filter(owned_by=self.request.user)
        return queryset


class PageListCreateAPIEndpoint(PageQuerysetMixin, BaseAPIView):
    """List and create the pages (wiki/docs) of a project"""

    permission_classes = [ProjectPagePermission]

    def get(self, request, slug, project_id):
        """List pages

        Filters: `parent=root|<page_id>`, `search=<text in the name>`, `archived=true` (archived only).
        Bodies are not included; fetch a page to read its `description_html`.
        """
        queryset = self.get_queryset()
        if request.GET.get("archived", "false").lower() == "true":
            queryset = queryset.filter(archived_at__isnull=False)
        else:
            queryset = queryset.filter(archived_at__isnull=True)
        parent = request.GET.get("parent")
        if parent == "root":
            queryset = queryset.filter(parent__isnull=True)
        elif parent:
            queryset = queryset.filter(parent_id=parent)
        search = request.GET.get("search", "").strip()
        if search:
            queryset = queryset.filter(name__icontains=search)

        return self.paginate(
            request=request,
            queryset=queryset.order_by("sort_order", "-created_at"),
            on_results=lambda pages: PageSerializer(pages, many=True, fields=self.fields).data,
        )

    def post(self, request, slug, project_id):
        """Create a page

        Accepts `name`, `description_html`, `access` (0 public, 1 private), `parent`, `kind` (page|folder)
        and `logo_props`. The collaborative document is built from `description_html` the first time
        the page is opened in the editor.
        """
        try:
            validate_new_parent(None, request.data.get("parent"), project_id, slug, request.user)
        except PageTreeError as e:
            return Response(e.as_response_data(), status=status.HTTP_400_BAD_REQUEST)

        data = {
            key: request.data[key] for key in ("name", "access", "parent", "kind", "logo_props") if key in request.data
        }
        description_html = request.data.get("description_html") or "<p></p>"
        serializer = AppPageSerializer(
            data=data,
            context={
                "project_id": project_id,
                "owned_by_id": request.user.id,
                "description_json": {},
                "description_binary": None,
                "description_html": description_html,
            },
        )
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        page = serializer.save()

        page_transaction.delay(
            new_description_html=page.description_html,
            old_description_html=None,
            page_id=str(page.id),
        )
        return Response(PageDetailSerializer(page).data, status=status.HTTP_201_CREATED)


class PageDetailAPIEndpoint(PageQuerysetMixin, BaseAPIView):
    """Read and update a page (wiki/docs)"""

    permission_classes = [ProjectPagePermission]

    def get(self, request, slug, project_id, page_id):
        """Get a page with its body (`description_html`)"""
        page = self.get_queryset().get(pk=page_id)
        return Response(PageDetailSerializer(page, fields=self.fields).data, status=status.HTTP_200_OK)

    def patch(self, request, slug, project_id, page_id):
        """Update a page

        `name` and `description_html` are applied to the page's collaborative document, so people
        editing it at the same time receive the change live and nothing they type is lost.
        `description_html` replaces the whole body: read the page first and send it back with
        only your edits. Also accepts `access` (owner only) and `logo_props`.
        """
        page = self.get_queryset().get(pk=page_id)

        if page.is_locked:
            return page_error("PAGE_LOCKED", "Page is locked")
        if page.archived_at:
            return page_error("PAGE_ARCHIVED", "Page is archived")

        serializer = PageUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        data = serializer.validated_data

        if "description_html" in data and page.is_folder:
            return page_error("PAGE_IS_FOLDER", "Folders have no content")
        if "access" in data and data["access"] != page.access and page.owned_by_id != request.user.id:
            return Response(
                {"error": "Access cannot be updated since this page is owned by someone else"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        old_description_html = page.description_html
        with transaction.atomic():
            # the row lock makes a concurrent save from the live server land after ours,
            # so the newest state of the document is the one that stays stored
            page = Page.objects.select_for_update().get(pk=page.id)

            content_changed = "description_html" in data or ("name" in data and data["name"] != page.name)
            if content_changed and not page.is_folder:
                try:
                    content = apply_page_content(
                        page,
                        description_html=data.get("description_html"),
                        name=data.get("name"),
                    )
                except LiveServerUnavailable:
                    return Response(
                        {"error": "The collaborative editor server is unavailable, try again later"},
                        status=status.HTTP_503_SERVICE_UNAVAILABLE,
                    )
                binary_serializer = PageBinaryUpdateSerializer(
                    page,
                    data={
                        "description_binary": content["description_binary"],
                        "description_html": content["description_html"],
                        "description_json": content["description_json"],
                    },
                    partial=True,
                )
                binary_serializer.is_valid(raise_exception=True)
                binary_serializer.save()

            for field in ("name", "access", "logo_props"):
                if field in data:
                    setattr(page, field, data[field])
            page.updated_by = request.user
            page.save()

        if page.description_html != old_description_html:
            page_transaction.delay(
                new_description_html=page.description_html,
                old_description_html=old_description_html,
                page_id=str(page_id),
            )
            track_page_version.delay(
                page_id=str(page_id),
                existing_instance=json.dumps({"description_html": old_description_html}, cls=DjangoJSONEncoder),
                user_id=request.user.id,
            )

        return Response(PageDetailSerializer(page).data, status=status.HTTP_200_OK)


class PageArchiveUnarchiveAPIEndpoint(PageQuerysetMixin, BaseAPIView):
    """Archive or restore a page together with its sub-pages"""

    permission_classes = [ProjectPagePermission]

    def _can_archive(self, request, project_id, page):
        # only the owner or a project admin
        return (
            page.owned_by_id == request.user.id
            or ProjectMember.objects.filter(
                project_id=project_id, member=request.user, is_active=True, role=ROLE.ADMIN.value
            ).exists()
        )

    def post(self, request, slug, project_id, page_id):
        """Archive a page and its sub-pages"""
        page = self.get_queryset().get(pk=page_id)
        if not self._can_archive(request, project_id, page):
            return Response(
                {"error": "Only the owner or admin can archive the page"},
                status=status.HTTP_403_FORBIDDEN,
            )
        UserFavorite.objects.filter(
            entity_type="page", entity_identifier=page_id, project_id=project_id, workspace__slug=slug
        ).delete()
        archived_at = timezone.now().date()
        archived_page_ids = set_archived_at_for_page_and_descendants(page_id, archived_at)
        return Response(
            {"archived_at": str(archived_at), "archived_page_ids": archived_page_ids},
            status=status.HTTP_200_OK,
        )

    def delete(self, request, slug, project_id, page_id):
        """Restore an archived page and its sub-pages"""
        page = self.get_queryset().get(pk=page_id)
        if not self._can_archive(request, project_id, page):
            return Response(
                {"error": "Only the owner or admin can restore the page"},
                status=status.HTTP_403_FORBIDDEN,
            )
        # restoring under an archived parent would break the tree: move it to the root
        if page.parent_id and page.parent.archived_at:
            page.parent = None
            page.save(update_fields=["parent"])
        restored_page_ids = set_archived_at_for_page_and_descendants(page_id, None)
        return Response({"restored_page_ids": restored_page_ids}, status=status.HTTP_200_OK)


class PageLockUnlockAPIEndpoint(PageQuerysetMixin, BaseAPIView):
    """Lock a page against edits, or unlock it"""

    permission_classes = [ProjectPagePermission]

    def post(self, request, slug, project_id, page_id):
        """Lock a page"""
        page = self.get_queryset().get(pk=page_id)
        if page.is_folder:
            return page_error("PAGE_IS_FOLDER", "Folders can't be locked")
        page.is_locked = True
        page.save(update_fields=["is_locked", "updated_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)

    def delete(self, request, slug, project_id, page_id):
        """Unlock a page"""
        page = self.get_queryset().get(pk=page_id)
        page.is_locked = False
        page.save(update_fields=["is_locked", "updated_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)
