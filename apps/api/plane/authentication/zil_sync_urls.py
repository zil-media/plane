# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.urls import path

from plane.authentication.views.zil_sync import (
    ZilWorkspaceSyncEndpoint,
    ZilUserSyncEndpoint,
    ZilUserLogoutEndpoint,
    ZilReconcileEndpoint,
)

urlpatterns = [
    path("sync/workspace/", ZilWorkspaceSyncEndpoint.as_view(), name="zil-sync-workspace"),
    path("sync/user/", ZilUserSyncEndpoint.as_view(), name="zil-sync-user"),
    path("sync/logout/", ZilUserLogoutEndpoint.as_view(), name="zil-sync-logout"),
    path("sync/reconcile/", ZilReconcileEndpoint.as_view(), name="zil-sync-reconcile"),
]
