# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Bearer-key auth for the cloud agent sessions and the CI lanes.

Each lane has its own key and each view accepts exactly one lane, so a key only reaches the
routes mounted for it: the feature key cannot touch bugs, and no key has an approve route.
Requests act as AGENT_ADMIN_EMAIL, so what a key can do is bounded by the routes alone.
"""

# Python imports
import hmac
import os

# Third party imports
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.throttling import SimpleRateThrottle

# Module imports
from plane.db.models import User


class AgentKeyAuthentication(BaseAuthentication):
    lane = ""
    env_var = ""

    def authenticate(self, request):
        header = request.META.get("HTTP_AUTHORIZATION", "")
        if not header.startswith("Bearer "):
            return None
        expected = os.environ.get(self.env_var, "")
        provided = header[len("Bearer ") :].strip()
        if not expected or not hmac.compare_digest(provided.encode(), expected.encode()):
            raise AuthenticationFailed("Invalid agent key.")

        email = os.environ.get("AGENT_ADMIN_EMAIL", "").strip()
        user = User.objects.filter(email=email, is_active=True).first() if email else None
        if user is None:
            raise AuthenticationFailed("Agent user is not configured.")
        return (user, self.lane)

    def authenticate_header(self, request):
        return "Bearer"


class BugAgentKeyAuthentication(AgentKeyAuthentication):
    lane = "bug"
    env_var = "OPS_BUG_AGENT_API_KEY"


class FeatureAgentKeyAuthentication(AgentKeyAuthentication):
    lane = "feature"
    env_var = "OPS_FEATURE_AGENT_API_KEY"


class AgentRateThrottle(SimpleRateThrottle):
    rate = "240/minute"

    def get_cache_key(self, request, view):
        return f"throttle_agent_{request.auth or 'anon'}"
