# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Third party imports
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

# Module imports
from plane.app.views.base import BaseAPIView
from plane.utils.zil_client import review_draft, zil_enabled

from .bug_report import _valid

# Mirror of MIN_REVIEWABLE in Workspace's reviewer: below this there's nothing to read yet.
MIN_REVIEWABLE = 40


class DraftReviewThrottle(UserRateThrottle):
    """20 drafts a minute per person: plenty to write, cuts any burst (the form debounces)."""

    rate = "20/minute"
    scope = "support_draft_review"


class DraftReviewSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=("bug", "feature"))
    title = serializers.CharField(required=False, allow_blank=True, max_length=200, default="")
    # No minimum: a short draft is the normal case (still typing) and is answered without a call.
    text = serializers.CharField(allow_blank=True, max_length=4000)
    screen = serializers.CharField(required=False, allow_blank=True, max_length=200, default="")


class SupportDraftReviewEndpoint(BaseAPIView):
    """Reads a bug report or a suggestion BEFORE it's sent and asks what's missing, right there.

    The model lives in Zil Workspace (one reviewer for both platforms); this relays to it with
    the service key. {"review": null} whenever there's no review — Zil not configured, the
    draft still too short, Zil down — and the form just doesn't show the panel.
    """

    throttle_classes = [DraftReviewThrottle]

    def post(self, request):
        data = _valid(DraftReviewSerializer, request)
        title, text = data["title"].strip(), data["text"].strip()
        if not zil_enabled() or len(title + text) < MIN_REVIEWABLE:
            return Response({"review": None})
        return Response({"review": review_draft(f"ops_{data['kind']}", title, text, data["screen"].strip())})
