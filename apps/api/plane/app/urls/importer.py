# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.urls import path

from plane.app.views import (
    NotionImportJobEndpoint,
    NotionImportJobDetailEndpoint,
    NotionImportJobRunEndpoint,
)


urlpatterns = [
    path(
        "workspaces/<str:slug>/imports/notion/",
        NotionImportJobEndpoint.as_view(),
        name="notion-imports",
    ),
    path(
        "workspaces/<str:slug>/imports/notion/<uuid:pk>/",
        NotionImportJobDetailEndpoint.as_view(),
        name="notion-import-detail",
    ),
    path(
        "workspaces/<str:slug>/imports/notion/<uuid:pk>/run/",
        NotionImportJobRunEndpoint.as_view(),
        name="notion-import-run",
    ),
]
