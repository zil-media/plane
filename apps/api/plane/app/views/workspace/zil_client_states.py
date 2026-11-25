# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""The model project whose states every client (brand) project of a workspace uses."""

# Django imports
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.app.permissions import ROLE, allow_permission
from plane.db.models import Project, Workspace, ZilClientStatesTemplate
from plane.utils.agent_pipeline.flags import is_feature_enabled
from plane.utils.zil_client_states import FLAG_KEY, apply_client_states, get_template, preview, template_states
from ..base import BaseAPIView


def _candidates(workspace_id):
    """Team projects a model can be picked from: neither a client nor the Migración project."""
    return Project.objects.filter(workspace_id=workspace_id, archived_at__isnull=True, zil_brand__isnull=True).order_by(
        "name"
    )


def _serialize_states(project):
    return [{"name": s.name, "color": s.color, "group": s.group} for s in template_states(project)]


class ZilClientStatesEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN], level="WORKSPACE")
    def get(self, request, slug):
        if not is_feature_enabled(FLAG_KEY):
            return Response(status=status.HTTP_404_NOT_FOUND)
        workspace = Workspace.objects.get(slug=slug)
        template = get_template(workspace.id)
        current = template.template_project if template else None
        candidates = [
            {"id": str(project.id), "name": project.name, "states": _serialize_states(project)}
            for project in _candidates(workspace.id)
        ]
        preview_project_id = request.query_params.get("template_project_id")
        preview_project = (
            _candidates(workspace.id).filter(pk=preview_project_id).first() if preview_project_id else current
        )
        return Response(
            {
                "template_project_id": str(current.id) if current else None,
                "applied_at": template.applied_at if template else None,
                "projects": candidates,
                "preview": preview(workspace.id, preview_project) if preview_project else None,
            },
            status=status.HTTP_200_OK,
        )

    @allow_permission([ROLE.ADMIN], level="WORKSPACE")
    def put(self, request, slug):
        if not is_feature_enabled(FLAG_KEY):
            return Response(status=status.HTTP_404_NOT_FOUND)
        workspace = Workspace.objects.get(slug=slug)
        project_id = request.data.get("template_project_id")
        try:
            project = _candidates(workspace.id).filter(pk=project_id).first() if project_id else None
        except (ValueError, ValidationError):
            project = None
        if project is None:
            return Response({"error": "Pick a team project of this workspace."}, status=status.HTTP_400_BAD_REQUEST)
        if not template_states(project):
            return Response({"error": "That project has no states."}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            template = get_template(workspace.id)
            if template is None:
                template = ZilClientStatesTemplate(workspace=workspace)
            template.template_project = project
            template.save()

        result = None
        if request.data.get("apply") is True:
            result = apply_client_states(workspace.id, project, request.user.id)
            ZilClientStatesTemplate.objects.filter(pk=template.pk).update(applied_at=timezone.now())
        return Response(
            {"template_project_id": str(project.id), "result": result},
            status=status.HTTP_200_OK,
        )
