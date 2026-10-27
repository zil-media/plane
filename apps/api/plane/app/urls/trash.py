# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.urls import path

from plane.app.views import (
    ProjectTrashEndpoint,
    ProjectTrashRestoreEndpoint,
    WorkspaceProjectTrashEndpoint,
    WorkspaceProjectTrashRestoreEndpoint,
)

urlpatterns = [
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/trash/",
        ProjectTrashEndpoint.as_view(),
        name="project-trash",
    ),
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/trash/<str:trash_type>/<uuid:pk>/restore/",
        ProjectTrashRestoreEndpoint.as_view(),
        name="project-trash-restore",
    ),
    path(
        "workspaces/<str:slug>/trash/projects/",
        WorkspaceProjectTrashEndpoint.as_view(),
        name="workspace-project-trash",
    ),
    path(
        "workspaces/<str:slug>/trash/projects/<uuid:pk>/restore/",
        WorkspaceProjectTrashRestoreEndpoint.as_view(),
        name="workspace-project-trash-restore",
    ),
]
