# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
from datetime import timedelta

# Django imports
from django.utils import timezone
from django.utils.dateparse import parse_datetime

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.authentication.views.zil_sync import ZilServiceView
from plane.db.models import Workspace
from plane.utils.zil_brand_projects import has_brand_roster
from plane.utils.zil_client_folders import apply_client_folders


# a roster stamped further ahead than this is a broken clock, not an order: taken in, it would
# make every real roster after it look older
MAX_CLOCK_AHEAD = timedelta(minutes=2)


def parse_computed_at(value):
    """The aware datetime of Zil's `computed_at` (ISO 8601), None when absent. ValueError when unusable."""
    if value in (None, ""):
        return None
    parsed = parse_datetime(value) if isinstance(value, str) else None
    if parsed is None or timezone.is_naive(parsed) or parsed > timezone.now() + MAX_CLOCK_AHEAD:
        raise ValueError("computed_at")
    return parsed


class ZilClientFoldersSyncEndpoint(ZilServiceView):
    """Zil pushes a workspace's client roster; every clients root of the workspace applies it.

    POST {workspace_slug, clients: [{id, alias, companyName, lifecycleStatus, businessUnitSlug}],
    authoritative, computed_at}. Only an authoritative roster archives folders of clients that left
    it. `computed_at` (ISO 8601, with zone) orders rosters: one older than what a root already
    applied is ignored (`stale` in the answer).

    A workspace that already got its brands as projects (POST sync/brand-projects/) has no clients
    folder any more: the push is answered `superseded` and changes nothing.
    """

    def post(self, request):
        slug = str(request.data.get("workspace_slug") or "").strip().lower()
        clients = request.data.get("clients")
        if not slug or not isinstance(clients, list):
            return Response({"error": "workspace_slug and clients[] required"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            computed_at = parse_computed_at(request.data.get("computed_at"))
        except ValueError:
            return Response(
                {"error": "computed_at must be an ISO 8601 time, not in the future"}, status=status.HTTP_400_BAD_REQUEST
            )
        workspace = Workspace.objects.filter(slug=slug).first()
        if workspace is None:
            return Response({"roots": 0, "workspace": "missing"}, status=status.HTTP_200_OK)
        if has_brand_roster(workspace.id):
            return Response({"roots": 0, "superseded": True}, status=status.HTTP_200_OK)
        stats = apply_client_folders(workspace.id, clients, request.data.get("authoritative") is True, computed_at)
        return Response(stats, status=status.HTTP_200_OK)
