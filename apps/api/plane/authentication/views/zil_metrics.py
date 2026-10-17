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
from plane.db.models import Workspace, WorkspaceMember
from plane.utils.zil_metrics import TZ, compute_person_metrics, compute_workspace_metrics

MAX_WINDOW_DAYS = 120


def _parse_day(value):
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _window(request):
    """(since, until) from ?since=&until= (Argentina days, `until` exclusive; default: the last
    28 days up to today), or None when it is not a valid window."""
    today = datetime.now(TZ).date()
    until = (
        _parse_day(request.query_params.get("until"))
        if request.query_params.get("until")
        else today + timedelta(days=1)
    )
    since = (
        _parse_day(request.query_params.get("since"))
        if request.query_params.get("since")
        else (until - timedelta(days=28) if until else None)
    )
    if since is None or until is None or since >= until or (until - since).days > MAX_WINDOW_DAYS:
        return None
    return since, until


BAD_WINDOW = {"error": f"since/until must be YYYY-MM-DD, since < until, at most {MAX_WINDOW_DAYS} days"}


def _workspace(request):
    slug = str(request.query_params.get("workspace_slug") or "").strip().lower()
    return Workspace.objects.filter(slug=slug).first() if slug else None


class ZilMetricsEndpoint(ZilServiceView):
    """Usage, interaction and timing metrics of a workspace for Zil Workspace.

    GET ?workspace_slug=&since=YYYY-MM-DD&until=YYYY-MM-DD (Argentina days, `until`
    exclusive; default: the last 28 days up to today).
    """

    # Service-key calls have no session, so DRF's default anon throttle (30/min per caller IP)
    # would answer 429 midway through Zil's 60-day backfill (two calls per workspace and day) and
    # its all-units view (two per workspace).
    throttle_classes = []

    def get(self, request):
        workspace = _workspace(request)
        if workspace is None:
            return Response({"error": "workspace_not_found"}, status=status.HTTP_404_NOT_FOUND)
        window = _window(request)
        if window is None:
            return Response(BAD_WINDOW, status=status.HTTP_400_BAD_REQUEST)
        return Response(compute_workspace_metrics(workspace, *window), status=status.HTTP_200_OK)


class ZilPersonMetricsEndpoint(ZilServiceView):
    """What one member did in a workspace: hours, active time, kind of work, what they owe.

    GET ?workspace_slug=&email=&since=&until= (same window as the workspace metrics). The person
    must be a member of the workspace.
    """

    throttle_classes = []

    def get(self, request):
        workspace = _workspace(request)
        if workspace is None:
            return Response({"error": "workspace_not_found"}, status=status.HTTP_404_NOT_FOUND)
        email = str(request.query_params.get("email") or "").strip()
        membership = (
            WorkspaceMember.objects.filter(workspace_id=workspace.id, member__email__iexact=email)
            .select_related("member")
            .first()
            if email
            else None
        )
        if membership is None:
            return Response({"error": "person_not_found"}, status=status.HTTP_404_NOT_FOUND)
        window = _window(request)
        if window is None:
            return Response(BAD_WINDOW, status=status.HTTP_400_BAD_REQUEST)
        return Response(compute_person_metrics(workspace, membership.member, *window), status=status.HTTP_200_OK)
