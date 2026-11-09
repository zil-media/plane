# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from .base import BaseSerializer
from plane.db.models import APIToken, APIActivityLog
from rest_framework import serializers
from django.utils import timezone


class APITokenSerializer(BaseSerializer):
    class Meta:
        model = APIToken
        fields = "__all__"
        read_only_fields = [
            "token",
            "expired_at",
            "created_at",
            "updated_at",
            "workspace",
            "user",
            "is_active",
            "last_used",
            "user_type",
            "allowed_rate_limit",
        ]


class APITokenReadSerializer(BaseSerializer):
    is_active = serializers.SerializerMethodField()
    # Zil Ops: the token of an app connected over MCP OAuth (Claude…). Its 24h expiry is renewed by
    # the app on its own, so it stays connected until it is deleted or the app is connected again.
    is_connector = serializers.SerializerMethodField()

    class Meta:
        model = APIToken
        exclude = ("token",)

    def get_is_connector(self, obj: APIToken) -> bool:
        return hasattr(obj, "mcp_oauth_grant")

    def get_is_active(self, obj: APIToken) -> bool:
        if self.get_is_connector(obj):
            return obj.is_active
        if obj.expired_at is None:
            return True
        return timezone.now() < obj.expired_at


class APIActivityLogSerializer(BaseSerializer):
    class Meta:
        model = APIActivityLog
        fields = "__all__"
