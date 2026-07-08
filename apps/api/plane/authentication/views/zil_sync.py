# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
Zil Workspace -> Plane sync API.

Event-driven, one-way sync (Zil is the source of truth). Zil calls these
endpoints whenever a Business Unit or a user's access changes, so Plane's
workspaces and memberships stay in step without waiting for the user's next
login. Authenticated with a shared service secret (constant-time compared),
never a per-user session — these are machine-to-machine.
"""

# Python imports
import hmac
import os

# Django imports
from django.db.models import Q

# Third party imports
from rest_framework import status
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

# Module imports
from plane.db.models import User
from plane.authentication.utils.zil_provisioning import (
    ensure_workspace,
    provision_user_workspaces,
    deactivate_user,
    deactivate_workspace,
    normalize_slug,
)
from plane.utils.exception_logger import log_exception


class ZilServicePermission(BasePermission):
    """Grants access only to callers presenting the correct X-Zil-Service-Key.

    Constant-time compared; fails closed when the secret is unset. Implemented
    as a DRF permission (rather than a dispatch override) so denials return a
    properly-rendered 401 instead of an unfinalized Response.
    """

    def has_permission(self, request, view):
        secret = os.environ.get("ZIL_SERVICE_SECRET")
        if not secret:
            return False
        provided = request.META.get("HTTP_X_ZIL_SERVICE_KEY", "")
        return hmac.compare_digest(str(provided), str(secret))


class ZilServiceView(APIView):
    """Base view for the Zil service-to-service sync endpoints."""

    permission_classes = [ZilServicePermission]


class ZilWorkspaceSyncEndpoint(ZilServiceView):
    """Upsert a Plane Workspace from a Zil Business Unit."""

    def post(self, request):
        slug = normalize_slug(request.data.get("slug"))
        if not slug:
            return Response({"error": "slug required"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            # active=false → the BU was deactivated in Zil; revoke workspace access.
            if request.data.get("active") is False:
                ws = deactivate_workspace(slug)
                return Response(
                    {"slug": slug, "deactivated": bool(ws)}, status=status.HTTP_200_OK
                )
            ws, created = ensure_workspace(
                slug=slug,
                name=request.data.get("name"),
                color=request.data.get("color"),
                logo_url=request.data.get("logo_url"),
            )
            return Response(
                {"slug": ws.slug, "workspace_id": str(ws.id), "created": created},
                status=status.HTTP_200_OK,
            )
        except Exception as e:
            log_exception(e)
            return Response({"error": "sync_failed"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class ZilUserSyncEndpoint(ZilServiceView):
    """Reconcile an existing Plane user's memberships / deprovision them.

    Only acts on users that already exist in Plane (i.e. have logged in at
    least once). Brand-new users are provisioned from their signed token on
    first login, so there is nothing to do here for them.
    """

    def post(self, request):
        email = str(request.data.get("email") or "").strip().lower()
        if not email:
            return Response({"error": "email required"}, status=status.HTTP_400_BAD_REQUEST)

        user = User.objects.filter(email=email, is_bot=False).first()
        if not user:
            return Response({"status": "skipped", "reason": "user_not_in_plane"}, status=status.HTTP_200_OK)

        try:
            if request.data.get("suspended"):
                deactivate_user(email)
                return Response({"status": "deactivated", "email": email}, status=status.HTTP_200_OK)

            # A sync/user call is Zil's confirmed desired state for the user, so
            # it's authoritative by default (empty list ⇒ revoke all). Zil may
            # send authoritative:false to explicitly signal a non-confirmed list.
            provision_user_workspaces(
                user,
                request.data.get("workspaces") or [],
                authoritative=request.data.get("authoritative", True),
            )
            return Response({"status": "synced", "email": email}, status=status.HTTP_200_OK)
        except Exception as e:
            log_exception(e)
            return Response({"error": "sync_failed"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class ZilReconcileEndpoint(ZilServiceView):
    """Full reconcile: upsert every workspace, then sync every existing user.

    Intended for a periodic (nightly) job as a backstop for missed events.
    """

    def post(self, request):
        workspaces = request.data.get("workspaces") or []
        users = request.data.get("users") or []

        ws_created, ws_failed = 0, 0
        for w in workspaces:
            try:
                _, created = ensure_workspace(
                    slug=w.get("slug"),
                    name=w.get("name"),
                    color=w.get("color"),
                    logo_url=w.get("logo_url"),
                )
                ws_created += int(created)
            except Exception as e:
                log_exception(e)
                ws_failed += 1

        users_synced, users_skipped, users_deactivated = 0, 0, 0
        for u in users:
            email = str(u.get("email") or "").strip().lower()
            if not email:
                continue
            existing = User.objects.filter(email=email, is_bot=False).first()
            if not existing:
                users_skipped += 1
                continue
            try:
                if u.get("suspended"):
                    deactivate_user(email)
                    users_deactivated += 1
                else:
                    # Reconcile is the authoritative nightly snapshot of desired
                    # state, so empty ⇒ revoke all for that user.
                    provision_user_workspaces(
                        existing, u.get("workspaces") or [], authoritative=u.get("authoritative", True)
                    )
                    users_synced += 1
            except Exception as e:
                log_exception(e)

        return Response(
            {
                "workspaces": {"total": len(workspaces), "created": ws_created, "failed": ws_failed},
                "users": {
                    "synced": users_synced,
                    "skipped": users_skipped,
                    "deactivated": users_deactivated,
                },
            },
            status=status.HTTP_200_OK,
        )
