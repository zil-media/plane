# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.authentication.views.zil_sync import ZilServiceView
from plane.db.models import Workspace
from plane.utils.zil_client_folders import apply_client_folders


class ZilClientFoldersSyncEndpoint(ZilServiceView):
    """Zil pushes a workspace's client roster; every clients root of the workspace applies it.

    POST {workspace_slug, clients: [{id, alias, companyName, lifecycleStatus, businessUnitSlug}],
    authoritative}. Only an authoritative roster archives folders of clients that left it.
    """

    def post(self, request):
        slug = str(request.data.get("workspace_slug") or "").strip().lower()
        clients = request.data.get("clients")
        if not slug or not isinstance(clients, list):
            return Response({"error": "workspace_slug and clients[] required"}, status=status.HTTP_400_BAD_REQUEST)
        workspace = Workspace.objects.filter(slug=slug).first()
        if workspace is None:
            return Response({"roots": 0, "workspace": "missing"}, status=status.HTTP_200_OK)
        stats = apply_client_folders(workspace.id, clients, request.data.get("authoritative") is True)
        return Response(stats, status=status.HTTP_200_OK)
