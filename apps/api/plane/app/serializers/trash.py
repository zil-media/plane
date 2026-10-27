# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Django imports
from django.conf import settings
from django.utils import timezone

# Third party imports
from rest_framework import serializers


class TrashItemSerializer(serializers.Serializer):
    """Read-only card for an item in the trash; works for every trashable model."""

    id = serializers.UUIDField()
    type = serializers.SerializerMethodField()
    name = serializers.CharField()
    sequence_id = serializers.SerializerMethodField()
    project_identifier = serializers.SerializerMethodField()
    deleted_at = serializers.DateTimeField()
    deleted_by_name = serializers.SerializerMethodField()
    days_remaining = serializers.SerializerMethodField()

    def get_type(self, obj):
        return self.context["trash_type"]

    def get_sequence_id(self, obj):
        return getattr(obj, "sequence_id", None)

    def get_project_identifier(self, obj):
        return self.context.get("project_identifier") or getattr(obj, "identifier", None)

    def get_deleted_by_name(self, obj):
        # No deleted_by column: the last editor is the closest approximation.
        user = obj.updated_by
        if user is None:
            return None
        return user.display_name or user.email

    def get_days_remaining(self, obj):
        elapsed = (timezone.now() - obj.deleted_at).days
        return max(settings.HARD_DELETE_AFTER_DAYS - elapsed, 0)
