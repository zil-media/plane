# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.urls import path

from plane.api.views.zil_page import (
    ApiMcpWhoAmIEndpoint,
    ApiPageSearchEndpoint,
    ApiPagesDescriptionViewSet,
    ApiPageViewSet,
)

urlpatterns = [
    path("zil-mcp/whoami/", ApiMcpWhoAmIEndpoint.as_view(), name="api-zil-mcp-whoami"),
    path("workspaces/<str:slug>/pages/search/", ApiPageSearchEndpoint.as_view(), name="api-page-search"),
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/pages/",
        ApiPageViewSet.as_view({"get": "list", "post": "create"}),
        name="api-project-pages",
    ),
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/pages/<uuid:page_id>/",
        ApiPageViewSet.as_view({"get": "retrieve", "patch": "partial_update", "delete": "destroy"}),
        name="api-project-page",
    ),
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/pages/<uuid:page_id>/archive/",
        ApiPageViewSet.as_view({"post": "archive", "delete": "unarchive"}),
        name="api-project-page-archive",
    ),
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/pages/<uuid:page_id>/lock/",
        ApiPageViewSet.as_view({"post": "lock", "delete": "unlock"}),
        name="api-project-page-lock",
    ),
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/pages/<uuid:page_id>/move-in-tree/",
        ApiPageViewSet.as_view({"post": "move_in_tree"}),
        name="api-project-page-move-in-tree",
    ),
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/pages/<uuid:page_id>/description/",
        ApiPagesDescriptionViewSet.as_view({"get": "retrieve", "patch": "partial_update"}),
        name="api-project-page-description",
    ),
]
