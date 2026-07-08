# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from .workspace_project_join import process_workspace_project_invitations
from plane.utils.exception_logger import log_exception


def post_user_auth_workflow(user, is_signup, request):
    process_workspace_project_invitations(user=user)

    # Converge non-token login paths (Google OAuth, magic link, email/password)
    # onto Zil BU->Workspace provisioning by fetching the user's context from
    # Zil. The Zil SSO path (/auth/zil/) already provisions from its signed
    # token in the endpoint, so skip it here to avoid a redundant round-trip.
    try:
        path = getattr(request, "path", "") or ""
        if not path.startswith("/auth/zil"):
            from plane.authentication.utils.zil_provisioning import (
                provision_user_from_zil,
            )

            provision_user_from_zil(user, request)
    except Exception as e:
        log_exception(e)
