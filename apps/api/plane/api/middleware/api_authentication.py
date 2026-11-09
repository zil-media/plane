# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Django imports
from django.utils import timezone
from django.db.models import Q

# Third party imports
from rest_framework import authentication
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied, Throttled

# Module imports
from plane.api.rate_limit import ApiAuthRateThrottle
from plane.db.models import APIToken


class APIKeyAuthentication(authentication.BaseAuthentication):
    """
    Authentication with an API Key
    """

    www_authenticate_realm = "api"
    media_type = "application/json"
    auth_header_name = "X-Api-Key"

    def get_api_token(self, request):
        return request.headers.get(self.auth_header_name)

    def validate_api_token(self, token):
        try:
            api_token = APIToken.objects.select_related("workspace", "mcp_oauth_grant").get(
                Q(Q(expired_at__gt=timezone.now()) | Q(expired_at__isnull=True)),
                token=token,
                is_active=True,
                user__is_active=True,
            )
        except APIToken.DoesNotExist:
            raise AuthenticationFailed("Given API token is not valid")

        # save api token last used
        api_token.last_used = timezone.now()
        api_token.save(update_fields=["last_used"])
        self.api_token = api_token
        return (api_token.user, api_token.token)

    @staticmethod
    def check_workspace_scope(api_token, request):
        """Zil Ops: an MCP connector granted for one workspace only works in that workspace.

        The MCP server already routes calls to the granted workspaces; this enforces it in the API
        too, so the token can't be used directly against another workspace the person belongs to.
        Personal tokens and connectors granted "all my workspaces" keep the person's full access.
        """
        try:
            grant = api_token.mcp_oauth_grant
        except APIToken.mcp_oauth_grant.RelatedObjectDoesNotExist:
            return
        if grant.all_workspaces or api_token.workspace is None:
            return
        match = getattr(request, "resolver_match", None)
        slug = match.kwargs.get("slug") if match else None
        if slug and slug != api_token.workspace.slug:
            raise PermissionDenied("This connection only has access to the workspace it was granted for.")

    def authenticate(self, request):
        # Throttle by IP before doing anything else, so that floods of
        # requests with no/invalid API keys are capped too (they never reach
        # ApiKeyRateThrottle since DRF checks auth before throttles).
        if not ApiAuthRateThrottle().allow_request(request, None):
            raise Throttled()

        token = self.get_api_token(request=request)
        if not token:
            return None

        # Validate the API token
        user, token = self.validate_api_token(token)
        self.check_workspace_scope(self.api_token, request)
        return user, token
