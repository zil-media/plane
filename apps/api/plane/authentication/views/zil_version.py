# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
import os

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.authentication.views.zil_sync import ZilServiceView


# what this build accepts, so Zil can tell an Ops behind it apart (and keep the old pushes for it)
ZIL_SYNC_FEATURES = ["brand-projects"]


class ZilVersionEndpoint(ZilServiceView):
    """The commit this Ops build was made from, so Zil can tell when the NAS is behind `preview`.

    GET → {"sha": "<40 hex>", "features": [...]}; empty when the image was built without GIT_SHA (a local build).
    The CI build (build-and-push.yml) passes the pushed commit as the GIT_SHA build arg.
    """

    def get(self, request):
        return Response(
            {"sha": os.environ.get("ZIL_OPS_GIT_SHA", ""), "features": ZIL_SYNC_FEATURES}, status=status.HTTP_200_OK
        )
