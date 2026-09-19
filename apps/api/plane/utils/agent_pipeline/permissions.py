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


class IsInstanceAdmin(BasePermission):
    """Bug triage, feature decisions and flags belong to instance admins."""

    def has_permission(self, request, view):
        return is_instance_admin(request.user)
