# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.urls import path

from .bugs import (
    AgentBugActionEndpoint,
    AgentBugBulkEndpoint,
    AgentBugDetailEndpoint,
    AgentBugListEndpoint,
    AgentPipelineIncidentEndpoint,
)
from .features import (
    AgentFeatureActionEndpoint,
    AgentFeatureDetailEndpoint,
    AgentFeatureListEndpoint,
)

urlpatterns = [
    path("bugs/", AgentBugListEndpoint.as_view(), name="agent-bugs"),
    path("bugs/pipeline-incident/", AgentPipelineIncidentEndpoint.as_view(), name="agent-pipeline-incident"),
    path("bugs/bulk/<str:action>/", AgentBugBulkEndpoint.as_view(), name="agent-bugs-bulk"),
    path("bugs/<uuid:pk>/", AgentBugDetailEndpoint.as_view(), name="agent-bug-detail"),
    path("bugs/<uuid:pk>/<str:action>/", AgentBugActionEndpoint.as_view(), name="agent-bug-action"),
    path("features/", AgentFeatureListEndpoint.as_view(), name="agent-features"),
    path("features/<uuid:pk>/", AgentFeatureDetailEndpoint.as_view(), name="agent-feature-detail"),
    path("features/<uuid:pk>/<str:action>/", AgentFeatureActionEndpoint.as_view(), name="agent-feature-action"),
]
