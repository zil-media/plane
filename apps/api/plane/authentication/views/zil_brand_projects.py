# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.authentication.views.zil_client_folders import parse_computed_at
from plane.authentication.views.zil_sync import ZilServiceView
from plane.db.models import Workspace
from plane.utils.zil_brand_projects import apply_brand_roster


class ZilBrandProjectsSyncEndpoint(ZilServiceView):
    """Zil pushes the brands a workspace works and who works on each: one private project per brand.

    POST {workspace_slug, brands: [{brandId, name, logo, color, status, members: [{email, role}],
    membersAuthoritative}], authoritative, computed_at, force?, dry_run?, template?}. No client data
    travels here. Answers the counters and one `{brandId, projectId, identifier, status, error}` per
    brand, so Zil can link the brand to its project. See plane.utils.zil_brand_projects.
    """

    def post(self, request):
        slug = str(request.data.get("workspace_slug") or "").strip().lower()
        brands = request.data.get("brands")
        if not slug or not isinstance(brands, list):
            return Response({"error": "workspace_slug and brands[] required"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            computed_at = parse_computed_at(request.data.get("computed_at"))
        except ValueError:
            return Response(
                {"error": "computed_at must be an ISO 8601 time, not in the future"}, status=status.HTTP_400_BAD_REQUEST
            )
        workspace = Workspace.objects.filter(slug=slug).first()
        if workspace is None:
            return Response({"workspace": "missing", "brands": []}, status=status.HTTP_200_OK)
        stats = apply_brand_roster(
            workspace.id,
            brands,
            authoritative=request.data.get("authoritative") is True,
            computed_at=computed_at,
            force=request.data.get("force") is True,
            dry_run=request.data.get("dry_run") is True,
            template=request.data.get("template"),
        )
        return Response(stats, status=status.HTTP_200_OK)
