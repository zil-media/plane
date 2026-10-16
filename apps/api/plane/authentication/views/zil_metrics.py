# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
from datetime import date, datetime, timedelta

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.authentication.views.zil_sync import ZilServiceView
from plane.db.models import Workspace
from plane.utils.zil_metrics import TZ, compute_workspace_metrics

MAX_WINDOW_DAYS = 120


def _parse_day(value):
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


class ZilMetricsEndpoint(ZilServiceView):
    """Usage, interaction and timing metrics of a workspace for Zil Workspace.

    GET ?workspace_slug=&since=YYYY-MM-DD&until=YYYY-MM-DD (Argentina days, `until`
    exclusive; default: the last 28 days up to today).
    """

    def get(self, request):
        slug = str(request.query_params.get("workspace_slug") or "").strip().lower()
        workspace = Workspace.objects.filter(slug=slug).first() if slug else None
        if workspace is None:
            return Response({"error": "workspace_not_found"}, status=status.HTTP_404_NOT_FOUND)

        today = datetime.now(TZ).date()
        until = (
            _parse_day(request.query_params.get("until"))
            if request.query_params.get("until")
            else today + timedelta(days=1)
        )
        since = (
            _parse_day(request.query_params.get("since"))
            if request.query_params.get("since")
            else until - timedelta(days=28)
        )
        if since is None or until is None or since >= until or (until - since).days > MAX_WINDOW_DAYS:
            return Response(
                {"error": f"since/until must be YYYY-MM-DD, since < until, at most {MAX_WINDOW_DAYS} days"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(compute_workspace_metrics(workspace, since, until), status=status.HTTP_200_OK)
