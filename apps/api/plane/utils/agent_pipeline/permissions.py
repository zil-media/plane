# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Third party imports
from rest_framework.permissions import BasePermission

# Module imports
from plane.license.models import Instance, InstanceAdmin


def is_instance_admin(user):
    if user is None or not user.is_authenticated:
        return False
    return InstanceAdmin.objects.filter(instance=Instance.objects.first(), role__gte=15, user=user).exists()


def is_workspace_director(user, workspace):
    """True when `user` runs the BU that `workspace` represents.

    The Zil role string ("director") never reaches this database: the SSO sync maps it to a
    Plane role int and drops it, and `director` and `admin` both land on Admin(20). What the
    sync does persist is ownership — it transfers each BU's workspace to its director — so
    ownership is the only durable signal of who runs one.
    """
    if user is None or workspace is None or not user.is_authenticated:
        return False
    return workspace.owner_id == user.id


class IsInstanceAdmin(BasePermission):
    """Bug triage, feature decisions and flags belong to instance admins."""

    def has_permission(self, request, view):
        return is_instance_admin(request.user)
