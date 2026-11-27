# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.urls import path

from plane.space.views.zil_portal import (
    PortalAssetEndpoint,
    PortalBrandEndpoint,
    PortalBrandsEndpoint,
    PortalCommentsEndpoint,
    PortalDocumentCommentsEndpoint,
    PortalDocumentEndpoint,
    PortalDocumentsEndpoint,
    PortalDraftEndpoint,
    PortalDraftsEndpoint,
    PortalDriveStreamEndpoint,
    PortalInviteEndpoint,
    PortalPostEndpoint,
    PortalPostsEndpoint,
    PortalSendChangesEndpoint,
)

urlpatterns = [
    path("portal/", PortalBrandsEndpoint.as_view(), name="zil-portal-brands"),
    path("portal/invite/<str:token>/", PortalInviteEndpoint.as_view(), name="zil-portal-invite"),
    path("portal/<uuid:project_id>/", PortalBrandEndpoint.as_view(), name="zil-portal-brand"),
    path("portal/<uuid:project_id>/posts/", PortalPostsEndpoint.as_view(), name="zil-portal-posts"),
    path("portal/<uuid:project_id>/posts/<uuid:issue_id>/", PortalPostEndpoint.as_view(), name="zil-portal-post"),
    path(
        "portal/<uuid:project_id>/posts/<uuid:issue_id>/comments/",
        PortalCommentsEndpoint.as_view(),
        name="zil-portal-comments",
    ),
    path("portal/<uuid:project_id>/documents/", PortalDocumentsEndpoint.as_view(), name="zil-portal-documents"),
    path(
        "portal/<uuid:project_id>/documents/<uuid:page_id>/",
        PortalDocumentEndpoint.as_view(),
        name="zil-portal-document",
    ),
    path(
        "portal/<uuid:project_id>/documents/<uuid:page_id>/comments/",
        PortalDocumentCommentsEndpoint.as_view(),
        name="zil-portal-document-comments",
    ),
    path(
        "portal/<uuid:project_id>/posts/<uuid:issue_id>/drafts/",
        PortalDraftsEndpoint.as_view(),
        name="zil-portal-drafts",
    ),
    path(
        "portal/<uuid:project_id>/posts/<uuid:issue_id>/drafts/<uuid:draft_id>/",
        PortalDraftEndpoint.as_view(),
        name="zil-portal-draft",
    ),
    path(
        "portal/<uuid:project_id>/posts/<uuid:issue_id>/send-changes/",
        PortalSendChangesEndpoint.as_view(),
        name="zil-portal-send-changes",
    ),
    path(
        "portal/<uuid:project_id>/posts/<uuid:issue_id>/drive/<str:file_id>/",
        PortalDriveStreamEndpoint.as_view(),
        name="zil-portal-drive-stream",
    ),
    path(
        "portal/<uuid:project_id>/assets/<uuid:asset_id>/",
        PortalAssetEndpoint.as_view(),
        name="zil-portal-asset",
    ),
]
