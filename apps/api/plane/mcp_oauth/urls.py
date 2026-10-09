# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.urls import path

from .views import AuthorizeRequestView, AuthorizeView, RegisterView, TokenView

urlpatterns = [
    path("register/", RegisterView.as_view(), name="mcp-oauth-register"),
    path("token/", TokenView.as_view(), name="mcp-oauth-token"),
    path("authorize/", AuthorizeView.as_view(), name="mcp-oauth-authorize"),
    path("authorize/<uuid:request_id>/", AuthorizeRequestView.as_view(), name="mcp-oauth-authorize-request"),
]
