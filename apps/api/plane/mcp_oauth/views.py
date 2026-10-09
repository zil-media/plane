# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Wiring for the MCP OAuth endpoints; the logic lives in service.py.

- /.well-known/oauth-authorization-server: discovery, public.
- /auth/mcp/register/ and /auth/mcp/token/: called by the connector's SERVER (Claude, ChatGPT)
  without a cookie. Their gate is the protocol's: known destinations to register, client + code +
  PKCE to redeem.
- /auth/mcp/authorize/: the consent screen, with the person's Ops session.
"""

# Python imports
import json
from urllib.parse import urlparse

# Django imports
from django.core.cache import cache
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import render
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

# Module imports
from plane.authentication.utils.host import base_host
from plane.db.models import Workspace
from plane.utils.path_validator import get_safe_redirect_url

from . import service
from .service import OAuthError

# per-IP calls to register/token per hour: generous for real clients, a wall for floods
RATE_LIMIT_PER_HOUR = 60


def _client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return forwarded.split(",")[0].strip() or request.META.get("REMOTE_ADDR", "")


def _rate_limited(request, bucket):
    key = f"mcp_oauth:{bucket}:{_client_ip(request)}"
    count = cache.get_or_set(key, 0, 3600)
    if count >= RATE_LIMIT_PER_HOUR:
        return True
    try:
        cache.incr(key)
    except ValueError:
        cache.set(key, 1, 3600)
    return False


def _oauth_error(error):
    response = JsonResponse({"error": error.code, "error_description": error.description}, status=error.status)
    response["Cache-Control"] = "no-store"
    return response


def _body(request):
    if request.content_type == "application/json":
        try:
            data = json.loads(request.body or b"{}")
        except json.JSONDecodeError:
            raise OAuthError("invalid_request", "Body is not valid JSON")
        if not isinstance(data, dict):
            raise OAuthError("invalid_request", "Body must be an object")
        return data
    return request.POST.dict()


class AuthorizationServerMetadataView(View):
    def get(self, request):
        return JsonResponse(service.authorization_server_metadata())


@method_decorator(csrf_exempt, name="dispatch")
class RegisterView(View):
    def post(self, request):
        if _rate_limited(request, "register"):
            return _oauth_error(OAuthError("slow_down", "Too many registrations, try again later", 429))
        try:
            return JsonResponse(service.register_client(_body(request)), status=201)
        except OAuthError as error:
            return _oauth_error(error)


@method_decorator(csrf_exempt, name="dispatch")
class TokenView(View):
    def post(self, request):
        if _rate_limited(request, "token"):
            return _oauth_error(OAuthError("slow_down", "Too many requests, try again later", 429))
        try:
            data = _body(request)
            client = service.authenticate_client(request, data)
            grant_type = data.get("grant_type")
            if grant_type == "authorization_code":
                payload = service.exchange_code(client, data)
            elif grant_type == "refresh_token":
                payload = service.refresh_access_token(client, data)
            else:
                raise OAuthError("unsupported_grant_type", f"Unsupported grant_type: {grant_type}")
        except OAuthError as error:
            return _oauth_error(error)
        response = JsonResponse(payload)
        response["Cache-Control"] = "no-store"
        response["Pragma"] = "no-cache"
        return response


def _error_page(request, error, status=400):
    return render(request, "mcp_oauth/authorize.html", {"error": error.description}, status=status)


class AuthorizeView(View):
    """Validates the client's request and parks it, so it survives the sign-in redirect."""

    def get(self, request):
        try:
            pending = service.create_pending_request(request.GET.dict())
        except OAuthError as error:
            return _error_page(request, error)
        return HttpResponseRedirect(f"/auth/mcp/authorize/{pending.id}/")


class AuthorizeRequestView(View):
    def _workspaces(self, user):
        return list(
            Workspace.objects.filter(
                workspace_member__member=user,
                workspace_member__is_active=True,
                workspace_member__deleted_at__isnull=True,
            )
            .distinct()
            .order_by("name")
        )

    def _sign_in(self, request, pending):
        return HttpResponseRedirect(
            get_safe_redirect_url(
                base_url=base_host(request=request, is_app=True),
                next_path=f"/auth/mcp/authorize/{pending.id}/",
                params={},
            )
        )

    def get(self, request, request_id):
        try:
            pending = service.get_pending_request(request_id)
        except OAuthError as error:
            return _error_page(request, error)
        if not request.user.is_authenticated:
            return self._sign_in(request, pending)
        workspaces = self._workspaces(request.user)
        if not workspaces:
            return _error_page(request, OAuthError("access_denied", "Tu usuario no pertenece a ningún espacio de Ops."))
        return render(
            request,
            "mcp_oauth/authorize.html",
            {
                "client_name": pending.client.client_name or "Una app",
                "redirect_host": urlparse(pending.params["redirect_uri"]).netloc or pending.params["redirect_uri"],
                "user": request.user,
                "workspaces": workspaces,
            },
        )

    def post(self, request, request_id):
        try:
            pending = service.get_pending_request(request_id)
        except OAuthError as error:
            return _error_page(request, error)
        if not request.user.is_authenticated:
            return self._sign_in(request, pending)
        allow = request.POST.get("decision") == "allow"
        workspace = None
        if allow:
            workspace = next(
                (w for w in self._workspaces(request.user) if w.slug == request.POST.get("workspace")), None
            )
            if workspace is None:
                return _error_page(request, OAuthError("invalid_request", "Elegí un espacio de trabajo válido."))
        try:
            return HttpResponseRedirect(service.decide_authorization(request.user, pending, workspace, allow))
        except OAuthError as error:
            return _error_page(request, error)
