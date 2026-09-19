# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.urls import path

from plane.app.views.support.bug_report import (
    BugReportAutoEndpoint,
    BugReportBulkEndpoint,
    BugReportDetailEndpoint,
    BugReportEndpoint,
    BugReportReopenEndpoint,
    BugReportSendToFixerEndpoint,
    MyBugReportsEndpoint,
)
from plane.app.views.support.feature_request import (
    AgentPipelineConfigEndpoint,
    FeatureFlagsEndpoint,
    FeatureRequestCommentEndpoint,
    FeatureRequestDecisionEndpoint,
    FeatureRequestDetailEndpoint,
    FeatureRequestEndpoint,
    FeatureRequestFlagEndpoint,
    FeatureRequestRespecEndpoint,
    SupportMeEndpoint,
)

urlpatterns = [
    path("support/me/", SupportMeEndpoint.as_view(), name="support-me"),
    path("support/config/", AgentPipelineConfigEndpoint.as_view(), name="support-config"),
    path("support/feature-flags/", FeatureFlagsEndpoint.as_view(), name="support-feature-flags"),
    path("support/bug-reports/", BugReportEndpoint.as_view(), name="support-bug-reports"),
    path("support/bug-reports/auto/", BugReportAutoEndpoint.as_view(), name="support-bug-reports-auto"),
    path("support/bug-reports/mine/", MyBugReportsEndpoint.as_view(), name="support-bug-reports-mine"),
    path("support/bug-reports/bulk/", BugReportBulkEndpoint.as_view(), name="support-bug-reports-bulk"),
    path("support/bug-reports/<uuid:pk>/", BugReportDetailEndpoint.as_view(), name="support-bug-report"),
    path(
        "support/bug-reports/<uuid:pk>/reopen/",
        BugReportReopenEndpoint.as_view(),
        name="support-bug-report-reopen",
    ),
    path(
        "support/bug-reports/<uuid:pk>/send-to-fixer/",
        BugReportSendToFixerEndpoint.as_view(),
        name="support-bug-report-send-to-fixer",
    ),
    path("support/feature-requests/", FeatureRequestEndpoint.as_view(), name="support-feature-requests"),
    path(
        "support/feature-requests/<uuid:pk>/",
        FeatureRequestDetailEndpoint.as_view(),
        name="support-feature-request",
    ),
    path(
        "support/feature-requests/<uuid:pk>/comments/",
        FeatureRequestCommentEndpoint.as_view(),
        name="support-feature-request-comments",
    ),
    path(
        "support/feature-requests/<uuid:pk>/respec/",
        FeatureRequestRespecEndpoint.as_view(),
        name="support-feature-request-respec",
    ),
    path(
        "support/feature-requests/<uuid:pk>/flag/",
        FeatureRequestFlagEndpoint.as_view(),
        name="support-feature-request-flag",
    ),
    path(
        "support/feature-requests/<uuid:pk>/<str:decision>/",
        FeatureRequestDecisionEndpoint.as_view(),
        name="support-feature-request-decision",
    ),
]
