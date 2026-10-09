# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.urls import path

from plane.api.views.zil_mcp import ApiMcpWhoAmIEndpoint, ApiPageSearchEndpoint

urlpatterns = [
    path("zil-mcp/whoami/", ApiMcpWhoAmIEndpoint.as_view(), name="api-zil-mcp-whoami"),
    path("workspaces/<str:slug>/pages/search/", ApiPageSearchEndpoint.as_view(), name="api-page-search"),
]
