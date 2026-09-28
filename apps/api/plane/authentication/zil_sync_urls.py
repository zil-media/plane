# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.urls import path

from plane.authentication.views.zil_sync import (
    ZilWorkspaceSyncEndpoint,
    ZilUserSyncEndpoint,
    ZilUserLogoutEndpoint,
    ZilReconcileEndpoint,
    ZilEntityLinkEndpoint,
    ZilAssetUrlEndpoint,
    ZilDocAttachEndpoint,
    ZilEntityCheckEndpoint,
    ZilErpAssetRedirectEndpoint,
    ZilErpLinksEndpoint,
    ZilErpOptionsEndpoint,
    ZilIssueErpRefsEndpoint,
)

urlpatterns = [
    path("sync/workspace/", ZilWorkspaceSyncEndpoint.as_view(), name="zil-sync-workspace"),
    path("sync/user/", ZilUserSyncEndpoint.as_view(), name="zil-sync-user"),
    path("sync/logout/", ZilUserLogoutEndpoint.as_view(), name="zil-sync-logout"),
    path("sync/reconcile/", ZilReconcileEndpoint.as_view(), name="zil-sync-reconcile"),
    path("sync/entity-link/", ZilEntityLinkEndpoint.as_view(), name="zil-sync-entity-link"),
    # service-key (Zil server → Plane): presigned-URL resolver + doc-attach chip
    path("sync/asset-url/", ZilAssetUrlEndpoint.as_view(), name="zil-sync-asset-url"),
    path("sync/doc-attach/", ZilDocAttachEndpoint.as_view(), name="zil-sync-doc-attach"),
    path("sync/entity-check/", ZilEntityCheckEndpoint.as_view(), name="zil-sync-entity-check"),
    # per-user session (Plane member → Zil doc): membership-gated 302
    path("erp-asset/", ZilErpAssetRedirectEndpoint.as_view(), name="zil-erp-asset"),
    # per-user session (web chip): ERP entities linked to a project/page
    path("erp-links/", ZilErpLinksEndpoint.as_view(), name="zil-erp-links"),
    # per-user session (work item "Cliente"/"Proyecto" properties): ERP-owned link, relayed
    path("erp-options/", ZilErpOptionsEndpoint.as_view(), name="zil-erp-options"),
    path("issue-erp-refs/", ZilIssueErpRefsEndpoint.as_view(), name="zil-issue-erp-refs"),
]
