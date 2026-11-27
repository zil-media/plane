# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from plane.db.models import Profile, Workspace, WorkspaceMember, WorkspaceMemberInvite


def get_redirection_path(user):
    # Handle redirections
    profile, _ = Profile.objects.get_or_create(user=user)

    # A brand's client contact belongs to no workspace: their place is the brand portal
    # (plane.utils.zil_client_portal), never the team's onboarding or "create workspace"
    if not WorkspaceMember.objects.filter(member=user, is_active=True).exists():
        from plane.utils.zil_client_portal import is_portal_client

        if is_portal_client(user):
            return "spaces/portal"

    # Redirect to onboarding if the user is not onboarded yet
    if not profile.is_onboarded:
        return "onboarding"

    # Redirect to the last workspace if the user has last workspace
    if (
        profile.last_workspace_id
        and Workspace.objects.filter(
            pk=profile.last_workspace_id,
            workspace_member__member_id=user.id,
            workspace_member__is_active=True,
        ).exists()
    ):
        workspace = Workspace.objects.filter(
            pk=profile.last_workspace_id,
            workspace_member__member_id=user.id,
            workspace_member__is_active=True,
        ).first()
        return f"{workspace.slug}"

    fallback_workspace = (
        Workspace.objects.filter(workspace_member__member_id=user.id, workspace_member__is_active=True)
        .order_by("created_at")
        .first()
    )
    # Redirect to fallback workspace
    if fallback_workspace:
        return f"{fallback_workspace.slug}"

    # Redirect to invitations if the user has unaccepted invitations
    if WorkspaceMemberInvite.objects.filter(email=user.email).count():
        return "invitations"

    # Redirect the user to create workspace
    return "create-workspace"
