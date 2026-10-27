# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Django imports
from django.conf import settings
from django.db import IntegrityError
from django.utils import timezone

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from .. import BaseAPIView
from .restore import restore_instance
from plane.app.permissions import ROLE, allow_permission
from plane.app.serializers.trash import TrashItemSerializer
from plane.db.models import Cycle, Issue, Module, Page, Project, ProjectPage, State
from plane.utils.agent_pipeline.flags import is_feature_enabled

TRASH_FLAG = "trashRestore"
PROJECT_TRASH_TYPES = ("issue", "page", "cycle", "module")


def _retention_cutoff():
    return timezone.now() - timezone.timedelta(days=settings.HARD_DELETE_AFTER_DAYS)


def _project_trash_queryset(trash_type, slug, project_id):
    cutoff = _retention_cutoff()
    if trash_type == "page":
        page_ids = ProjectPage.all_objects.filter(project_id=project_id, workspace__slug=slug).values("page_id")
        queryset = Page.all_objects.filter(id__in=page_ids)
    else:
        model = {"issue": Issue, "cycle": Cycle, "module": Module}[trash_type]
        queryset = model.all_objects.filter(project_id=project_id, workspace__slug=slug)
    return queryset.filter(deleted_at__isnull=False, deleted_at__gte=cutoff).select_related("updated_by")


class ProjectTrashEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN])
    def get(self, request, slug, project_id):
        if not is_feature_enabled(TRASH_FLAG):
            return Response(status=status.HTTP_404_NOT_FOUND)

        trash_type = request.query_params.get("type", "issue")
        if trash_type not in PROJECT_TRASH_TYPES:
            return Response({"error": "Invalid type"}, status=status.HTTP_400_BAD_REQUEST)

        project = Project.objects.filter(pk=project_id, workspace__slug=slug).first()
        if project is None:
            return Response({"error": "Project not found"}, status=status.HTTP_404_NOT_FOUND)

        items = _project_trash_queryset(trash_type, slug, project_id).order_by("-deleted_at")[:200]
        serializer = TrashItemSerializer(
            items,
            many=True,
            context={"trash_type": trash_type, "project_identifier": project.identifier},
        )
        return Response(serializer.data, status=status.HTTP_200_OK)


class ProjectTrashRestoreEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN])
    def post(self, request, slug, project_id, trash_type, pk):
        if not is_feature_enabled(TRASH_FLAG):
            return Response(status=status.HTTP_404_NOT_FOUND)

        if trash_type not in PROJECT_TRASH_TYPES:
            return Response({"error": "Invalid type"}, status=status.HTTP_400_BAD_REQUEST)

        obj = _project_trash_queryset(trash_type, slug, project_id).filter(pk=pk).first()
        if obj is None:
            return Response(
                {"error": "The item is not in the trash or can no longer be recovered"},
                status=status.HTTP_404_NOT_FOUND,
            )

        if (
            trash_type == "issue"
            and obj.state_id
            and State.all_objects.filter(pk=obj.state_id).exclude(deleted_at__isnull=True).exists()
        ):
            return Response(
                {"error": "The state of this work item was deleted. Recreate the state before restoring."},
                status=status.HTTP_409_CONFLICT,
            )

        try:
            restore_instance(obj)
        except IntegrityError:
            return Response(
                {"error": "Another item with the same name or identifier already exists"},
                status=status.HTTP_409_CONFLICT,
            )
        return Response({"id": str(pk), "type": trash_type}, status=status.HTTP_200_OK)


class WorkspaceProjectTrashEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN], level="WORKSPACE")
    def get(self, request, slug):
        if not is_feature_enabled(TRASH_FLAG):
            return Response(status=status.HTTP_404_NOT_FOUND)

        projects = (
            Project.all_objects.filter(
                workspace__slug=slug, deleted_at__isnull=False, deleted_at__gte=_retention_cutoff()
            )
            .select_related("updated_by")
            .order_by("-deleted_at")[:200]
        )
        serializer = TrashItemSerializer(projects, many=True, context={"trash_type": "project"})
        return Response(serializer.data, status=status.HTTP_200_OK)


class WorkspaceProjectTrashRestoreEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN], level="WORKSPACE")
    def post(self, request, slug, pk):
        if not is_feature_enabled(TRASH_FLAG):
            return Response(status=status.HTTP_404_NOT_FOUND)

        project = Project.all_objects.filter(
            pk=pk, workspace__slug=slug, deleted_at__isnull=False, deleted_at__gte=_retention_cutoff()
        ).first()
        if project is None:
            return Response(
                {"error": "The project is not in the trash or can no longer be recovered"},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            restore_instance(project)
        except IntegrityError:
            return Response(
                {"error": "Another project with the same identifier already exists"},
                status=status.HTTP_409_CONFLICT,
            )
        return Response({"id": str(pk), "type": "project"}, status=status.HTTP_200_OK)
