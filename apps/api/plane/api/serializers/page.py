# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Third party imports
from rest_framework import serializers

# Module imports
from plane.db.models import Page
from plane.utils.content_validator import validate_html_content
from .base import BaseSerializer


class PageSerializer(BaseSerializer):
    """Page (wiki/docs) metadata. The body is only returned by the detail serializer."""

    class Meta:
        model = Page
        fields = [
            "id",
            "name",
            "kind",
            "access",
            "parent",
            "owned_by",
            "is_locked",
            "archived_at",
            "logo_props",
            "sort_order",
            "workspace",
            "created_at",
            "updated_at",
            "created_by",
            "updated_by",
        ]
        read_only_fields = fields


class PageDetailSerializer(PageSerializer):
    class Meta(PageSerializer.Meta):
        fields = PageSerializer.Meta.fields + ["description_html"]
        read_only_fields = fields


class PageUpdateSerializer(serializers.Serializer):
    """Fields a page can be updated with through the public API."""

    name = serializers.CharField(required=False, allow_blank=True)
    description_html = serializers.CharField(required=False, allow_blank=True)
    access = serializers.ChoiceField(choices=Page.ACCESS_CHOICES, required=False)
    logo_props = serializers.JSONField(required=False)

    def validate_description_html(self, value):
        if not value:
            return "<p></p>"
        is_valid, error_message, sanitized_html = validate_html_content(value)
        if not is_valid:
            raise serializers.ValidationError(error_message)
        return sanitized_html if sanitized_html is not None else value
