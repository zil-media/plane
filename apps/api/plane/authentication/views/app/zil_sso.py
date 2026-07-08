# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
import os
import time

# Django imports
from django.http import HttpResponseRedirect
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

# Third party imports
import jwt

# Module imports
from plane.authentication.adapter.error import (
    AUTHENTICATION_ERROR_CODES,
    AuthenticationException,
)
from plane.authentication.provider.credentials.zil_sso import ZilSSOProvider
from plane.authentication.utils.host import base_host
from plane.authentication.utils.login import user_login
from plane.authentication.utils.redirection_path import get_redirection_path
from plane.authentication.utils.user_auth_workflow import post_user_auth_workflow
from plane.authentication.utils.zil_provisioning import provision_user_workspaces
from plane.utils.exception_logger import log_exception
from plane.license.models import Instance
from plane.settings.redis import redis_instance
from plane.utils.path_validator import get_safe_redirect_url

# Expected audience / issuer of the SSO token minted by Zil Workspace.
ZIL_SSO_AUDIENCE = "plane"
ZIL_SSO_ISSUER = "zil-workspace"
# Upper bound on how long a used jti is remembered for replay protection.
# Tokens themselves are short-lived (~60s); this is a safety ceiling in case
# the exp claim is missing or malformed.
ZIL_SSO_JTI_MAX_TTL = 600


@method_decorator(csrf_exempt, name="dispatch")
class ZilSSOEndpoint(View):
    """Trusted single-sign-on entrypoint for Zil Workspace.

    Flow: Zil Workspace mints a short-lived JWT (signed with the shared
    ``PLANE_SSO_SECRET``) and redirects the browser here with ``?token=<jwt>``.
    We verify the signature / audience / issuer / expiry, enforce one-time use
    via the ``jti`` claim, then provision-or-login the user and set the Django
    session cookie before redirecting into the app.
    """

    def _redirect_with_error(self, request, error_code_key, next_path=None, email=None):
        exc = AuthenticationException(
            error_code=AUTHENTICATION_ERROR_CODES[error_code_key],
            error_message=error_code_key,
            payload={"email": email} if email else {},
        )
        url = get_safe_redirect_url(
            base_url=base_host(request=request, is_app=True),
            next_path=next_path,
            params=exc.get_error_dict(),
        )
        return HttpResponseRedirect(url)

    def _handle(self, request, token, next_path):
        # Instance must be set up before we can provision users
        instance = Instance.objects.first()
        if instance is None or not instance.is_setup_done:
            return self._redirect_with_error(
                request, "INSTANCE_NOT_CONFIGURED", next_path
            )

        secret = os.environ.get("PLANE_SSO_SECRET")
        if not secret:
            return self._redirect_with_error(
                request, "ZIL_SSO_NOT_CONFIGURED", next_path
            )

        if not token:
            return self._redirect_with_error(
                request, "ZIL_SSO_INVALID_TOKEN", next_path
            )

        # Verify signature, audience, issuer and expiry in one shot.
        try:
            claims = jwt.decode(
                token,
                secret,
                algorithms=["HS256"],
                audience=ZIL_SSO_AUDIENCE,
                issuer=ZIL_SSO_ISSUER,
                options={"require": ["exp", "jti", "email"]},
            )
        except jwt.PyJWTError:
            return self._redirect_with_error(
                request, "ZIL_SSO_INVALID_TOKEN", next_path
            )

        email = (claims.get("email") or "").strip().lower()
        if not email:
            return self._redirect_with_error(
                request, "ZIL_SSO_INVALID_TOKEN", next_path
            )

        # One-time use: atomically claim the jti. SET NX returns False if the
        # key already exists, meaning the token was already redeemed (replay).
        jti = claims.get("jti")
        exp = claims.get("exp")
        ttl = ZIL_SSO_JTI_MAX_TTL
        if isinstance(exp, (int, float)):
            remaining = int(exp - time.time())
            # Clamp: at least 1s so the key is actually stored, at most the ceiling.
            ttl = max(1, min(remaining, ZIL_SSO_JTI_MAX_TTL))
        # Redis is a hard dependency for replay protection. If it's unreachable,
        # fail closed with a clean redirect — never let the exception bubble into
        # a raw 500 (which would leak a traceback on this public endpoint).
        try:
            ri = redis_instance()
            claimed = ri.set(f"zil_sso_jti:{jti}", "1", nx=True, ex=ttl)
        except Exception as e:
            log_exception(e)
            return self._redirect_with_error(request, "ZIL_SSO_NOT_CONFIGURED", next_path)
        if not claimed:
            return self._redirect_with_error(
                request, "ZIL_SSO_TOKEN_REUSED", next_path, email=email
            )

        try:
            provider = ZilSSOProvider(
                request=request,
                email=email,
                claims=claims,
                callback=post_user_auth_workflow,
            )
            user = provider.authenticate()

            # BU -> Workspace provisioning (Fase 2). The desired workspace list
            # is carried in the signed token, so no callback to Zil is needed.
            # Failure here must not block login — the user still lands on Plane's
            # onboarding as a fallback.
            try:
                provision_user_workspaces(user, claims.get("workspaces") or [])
            except Exception as e:
                log_exception(e)

            # Set the Django session cookie
            user_login(request=request, user=user, is_app=True)
            path = str(next_path) if next_path else str(get_redirection_path(user=user))
            url = get_safe_redirect_url(
                base_url=base_host(request=request, is_app=True),
                next_path=path,
                params={},
            )
            return HttpResponseRedirect(url)
        except AuthenticationException as e:
            url = get_safe_redirect_url(
                base_url=base_host(request=request, is_app=True),
                next_path=next_path,
                params=e.get_error_dict(),
            )
            return HttpResponseRedirect(url)
        except Exception as e:
            # Any unexpected (likely transient) failure after the jti was claimed
            # — DB blip, avatar-fetch timeout, provisioning callback, etc. — must
            # redirect with a readable error instead of a raw 500 traceback.
            # Release the jti so the SAME token can be retried within its short
            # exp window (deterministic failures raise AuthenticationException
            # above and keep the token spent; only unexpected errors land here).
            log_exception(e)
            try:
                ri.delete(f"zil_sso_jti:{jti}")
            except Exception:
                pass
            return self._redirect_with_error(
                request, "AUTHENTICATION_FAILED", next_path, email=email
            )

    def get(self, request):
        token = request.GET.get("token", "").strip()
        next_path = request.GET.get("next_path")
        return self._handle(request, token, next_path)

    def post(self, request):
        token = request.POST.get("token", "").strip()
        next_path = request.POST.get("next_path")
        return self._handle(request, token, next_path)
