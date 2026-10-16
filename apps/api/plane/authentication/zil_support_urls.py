# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.urls import path

from plane.authentication.views.zil_support import ZilSupportTrackingEndpoint

urlpatterns = [
    # service-key (Zil Workspace "Seguimiento"): one person's suggestions, read-only
    path("sync/support-tracking/", ZilSupportTrackingEndpoint.as_view(), name="zil-sync-support-tracking"),
]
