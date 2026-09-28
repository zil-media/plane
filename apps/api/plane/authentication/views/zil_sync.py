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
import time
import uuid
from urllib.parse import quote

# Django imports
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.http import HttpResponseRedirect

# Third party imports
import requests
from rest_framework import status
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

# Module imports
from plane.db.models import User, Issue, IssueLink, Project, Page, FileAsset, WorkspaceMember
from plane.settings.storage import S3Storage
from plane.authentication.utils.zil_provisioning import (
    ensure_workspace,
    provision_user_workspaces,
    deactivate_user,
    deactivate_workspace,
    revoke_user_sessions,
    normalize_slug,
)
from plane.utils.exception_logger import log_exception
from plane.utils.zil_client import (
    ZilUnavailable,
    get_issue_erp_refs,
    is_valid_client_id,
    search_zil_clients,
    search_zil_projects,
    set_issue_erp_ref,
    zil_enabled,
)


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

            # A per-user event webhook is a PARTIAL signal by nature (one user
            # changed), so it is NON-authoritative by default: it adds/updates
            # the memberships it names but never revokes the ones it omits. This
            # prevents a partial/truncated payload from wiping a live user's
            # access mid-session. Zil must send authoritative:true explicitly to
            # request a full per-user reconcile; genuine deprovision also has
            # explicit paths (suspended → deactivate_user, BU off →
            # ZilWorkspaceSyncEndpoint), and the nightly reconcile is authoritative.
            provision_user_workspaces(
                user,
                request.data.get("workspaces") or [],
                authoritative=request.data.get("authoritative", False),
            )
            return Response({"status": "synced", "email": email}, status=status.HTTP_200_OK)
        except Exception as e:
            log_exception(e)
            return Response({"error": "sync_failed"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class ZilUserLogoutEndpoint(ZilServiceView):
    """Kill every live Plane (Ops) session for a user, on an explicit Zil sign-out.

    True single sign-out: signing out of Zil Workspace should not leave an
    already-open Ops tab authenticated for up to SESSION_COOKIE_AGE (7 days).
    This does NOT deactivate the user or touch workspace memberships — it only
    revokes sessions, so a still-valid user is simply signed out everywhere and
    can log back in immediately. Full deprovision remains ZilUserSyncEndpoint's
    `suspended` path (deactivate_user), which also revokes sessions itself.
    """

    def post(self, request):
        email = str(request.data.get("email") or "").strip().lower()
        if not email:
            return Response({"error": "email required"}, status=status.HTTP_400_BAD_REQUEST)

        user = User.objects.filter(email=email, is_bot=False).first()
        if not user:
            return Response({"status": "skipped", "reason": "user_not_in_plane"}, status=status.HTTP_200_OK)

        try:
            revoked = revoke_user_sessions(user)
            return Response(
                {"status": "logged_out", "email": email, "sessions_revoked": revoked},
                status=status.HTTP_200_OK,
            )
        except Exception as e:
            log_exception(e)
            return Response({"error": "logout_failed"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


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
                    # state, so it revokes memberships not in the list. An empty
                    # list is treated as a partial/truncated payload by
                    # provision_user_workspaces's own guard and revokes nothing
                    # (see its docstring) — it does NOT wipe the user's access.
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


class ZilEntityLinkEndpoint(ZilServiceView):
    """Set/clear a Plane content back-reference for an ERP↔Ops entity link.

    The link itself is owned by Zil Workspace (golden rule); this endpoint only
    stamps/clears Plane's disposable external_source/external_id back-ref (and,
    for issues, a native IssueLink chip). Supports issue, project and page.
    See docs/plan/erp-ops-linking/PLAN.md.
    """

    # Each linkable Plane content type carries external_source/external_id; only
    # issues also get a visible IssueLink chip (project/page have no link table).
    _MODELS = {"issue": Issue, "project": Project, "page": Page}

    def post(self, request):
        op = request.data.get("op")
        entity_type = request.data.get("plane_entity_type")
        slug = request.data.get("workspace_slug")
        entity_id = request.data.get("plane_entity_id")
        opslink_id = request.data.get("opslink_id")
        url = request.data.get("url")
        title = (request.data.get("title") or "Zil")[:255]

        if entity_type not in self._MODELS:
            return Response(
                {"error": "unsupported_entity_type", "detail": f"'{entity_type}' is not linkable."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if op not in ("set", "clear"):
            return Response(
                {"error": "unsupported_op", "detail": f"'{op}' is not a valid op."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            # scope to the claimed workspace; 404 (not 403) avoids leaking
            # cross-workspace existence — this view runs outside per-user auth
            obj = self._MODELS[entity_type].objects.filter(pk=entity_id, workspace__slug=slug).first()
            if obj is None:
                return Response({"error": "not_found"}, status=status.HTTP_404_NOT_FOUND)

            if op == "set":
                obj.external_source = "zil"
                obj.external_id = opslink_id
                obj.save(update_fields=["external_source", "external_id"])
                if entity_type == "issue":
                    # idempotent on (issue, url) — a retry never duplicates the chip
                    IssueLink.objects.get_or_create(
                        issue=obj,
                        url=url,
                        defaults={"title": title, "workspace": obj.workspace, "project": obj.project},
                    )
                return Response({"status": "linked"}, status=status.HTTP_200_OK)

            # op == "clear": only ever clear OUR own back-ref, and only if it still
            # points at THIS link — a newer link (different opslink_id) is left intact.
            if obj.external_source == "zil" and str(obj.external_id or "") == str(opslink_id or ""):
                obj.external_source = None
                obj.external_id = None
                obj.save(update_fields=["external_source", "external_id"])
            if entity_type == "issue" and url:
                # remove just this chip; other links on the issue are untouched
                IssueLink.objects.filter(issue=obj, url=url).delete()
            return Response({"status": "cleared"}, status=status.HTTP_200_OK)
        except Exception as e:
            log_exception(e)
            return Response({"error": "entity_link_failed"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class ZilAssetUrlEndpoint(ZilServiceView):
    """Resolve a Plane file asset to a short-lived presigned URL, for Zil.

    Server-to-server only (service key): Zil's authenticated proxy route calls
    this and 302-redirects its own user, so Plane's storage origin and
    credentials never reach a browser via Zil. Returns JSON (not a redirect)
    because the consumer is the Zil server, not a browser.
    """

    def get(self, request):
        slug = request.query_params.get("workspace_slug")
        asset_id = request.query_params.get("asset_id")
        if not slug or not asset_id:
            return Response(
                {"error": "workspace_slug and asset_id required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            asset = FileAsset.objects.filter(
                pk=asset_id, workspace__slug=slug, is_uploaded=True, is_deleted=False
            ).first()
            if asset is None:
                return Response({"error": "not_found"}, status=status.HTTP_404_NOT_FOUND)
            storage = S3Storage(request=request)
            signed_url = storage.generate_presigned_url(
                object_name=asset.asset.name,
                disposition="attachment",
                filename=asset.attributes.get("name"),
            )
            return Response(
                {
                    "url": signed_url,
                    "name": asset.attributes.get("name"),
                    "type": asset.attributes.get("type"),
                    "size": asset.size,
                },
                status=status.HTTP_200_OK,
            )
        except Exception as e:
            log_exception(e)
            return Response({"error": "asset_url_failed"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class ZilDocAttachEndpoint(ZilServiceView):
    """Attach/detach a Zil-stored document to a Plane issue, as a link chip.

    Golden rule: the bytes stay in Zil's storage — Plane only gets an IssueLink
    whose URL points at ZilErpAssetRedirectEndpoint (membership-gated redirect
    to a presigned URL). metadata carries the Zil object key + owning link id
    so 'clear' removes exactly this chip and the redirect can authorize reads.
    """

    def post(self, request):
        op = request.data.get("op")
        slug = request.data.get("workspace_slug")
        issue_id = request.data.get("issue_id")
        key = request.data.get("key")
        link_id = request.data.get("link_id")
        title = (request.data.get("name") or "Zil document")[:255]

        if op not in ("set", "clear") or not slug or not issue_id or not link_id:
            return Response({"error": "invalid_payload"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            issue = Issue.objects.filter(pk=issue_id, workspace__slug=slug).first()
            if issue is None:
                return Response({"error": "not_found"}, status=status.HTTP_404_NOT_FOUND)

            if op == "set":
                if not key:
                    return Response({"error": "key required"}, status=status.HTTP_400_BAD_REQUEST)
                # Unique per link (retry-idempotent via get_or_create on url):
                # the same doc attached from two ERP contexts keeps two chips,
                # each cleared only by its own link.
                base = (os.environ.get("WEB_URL") or "").rstrip("/")
                url = f"{base}/api/zil/erp-asset/?key={quote(key, safe='')}&link={link_id}"
                IssueLink.objects.get_or_create(
                    issue=issue,
                    url=url,
                    defaults={
                        "title": title,
                        "metadata": {"zil_key": key, "zil_link_id": link_id},
                        "workspace": issue.workspace,
                        "project": issue.project,
                    },
                )
                return Response({"status": "attached"}, status=status.HTTP_200_OK)

            IssueLink.objects.filter(issue=issue, metadata__zil_link_id=link_id).delete()
            return Response({"status": "detached"}, status=status.HTTP_200_OK)
        except Exception as e:
            log_exception(e)
            return Response({"error": "doc_attach_failed"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class ZilEntityCheckEndpoint(ZilServiceView):
    """Existence check for linked Plane entities — read-only drift monitor.

    Zil's planeLinkHealthCheck posts the entities its planeLinks[] reference;
    we return the ids that no longer resolve (deleted entity, wrong workspace)
    so the ERP can flag stale links. Never mutates anything.
    """

    _MODELS = {"issue": Issue, "project": Project, "page": Page}
    _MAX_ITEMS = 500

    def post(self, request):
        items = request.data.get("items")
        if not isinstance(items, list) or len(items) > self._MAX_ITEMS:
            return Response({"error": "invalid_items"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            missing = []
            for item in items:
                model = self._MODELS.get(item.get("type"))
                entity_id = item.get("id")
                slug = item.get("slug")
                if model is None or not entity_id or not slug:
                    missing.append(entity_id)
                    continue
                try:
                    exists = model.objects.filter(pk=entity_id, workspace__slug=slug).exists()
                except (ValueError, ValidationError):
                    exists = False  # malformed uuid → counts as missing
                if not exists:
                    missing.append(entity_id)
            return Response({"missing": missing}, status=status.HTTP_200_OK)
        except Exception as e:
            log_exception(e)
            return Response({"error": "entity_check_failed"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class ZilErpLinksEndpoint(APIView):
    """ERP entities linked to a Plane project/page, for the web 'Zil' chip.

    Per-user session auth. The entity is resolved through the requester's OWN
    membership (project members for projects; workspace members for pages, and
    private pages only for their owner) — 404 otherwise, mirroring the app's
    no-existence-leak convention. When the entity carries our back-ref
    (external_source='zil'), the ERP resolves the live names/urls via the
    service bridge; results are memoized in-process for ~45s (no persisted
    cache — the ERP stays the single source of truth).
    """

    permission_classes = [IsAuthenticated]

    # entity_id -> (expires_at_monotonic, links). Tiny + self-pruning: cleared
    # wholesale if it ever grows past _CACHE_MAX (45s entries — rebuild is cheap).
    _CACHE = {}
    _CACHE_TTL = 45
    _CACHE_MAX = 512

    def get(self, request):
        entity_type = request.query_params.get("entity_type")
        entity_id = request.query_params.get("entity_id")
        try:
            uuid.UUID(str(entity_id))
        except ValueError:
            return Response({"error": "invalid_entity_id"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            if entity_type == "project":
                obj = Project.objects.filter(
                    pk=entity_id,
                    project_projectmember__member=request.user,
                    project_projectmember__is_active=True,
                ).first()
            elif entity_type == "page":
                obj = (
                    Page.objects.filter(
                        pk=entity_id,
                        workspace__workspace_member__member=request.user,
                        workspace__workspace_member__is_active=True,
                    )
                    .filter(Q(access=0) | Q(owned_by=request.user))
                    .first()
                )
            else:
                return Response({"error": "invalid_entity_type"}, status=status.HTTP_400_BAD_REQUEST)

            if obj is None:
                return Response({"error": "not_found"}, status=status.HTTP_404_NOT_FOUND)
            if obj.external_source != "zil":
                return Response({"links": []}, status=status.HTTP_200_OK)

            cache_key = str(entity_id)
            hit = self._CACHE.get(cache_key)
            if hit and hit[0] > time.monotonic():
                return Response({"links": hit[1]}, status=status.HTTP_200_OK)

            base = os.environ.get("ZIL_BASE_URL")
            secret = os.environ.get("ZIL_SERVICE_SECRET")
            if not base or not secret:
                return Response({"links": []}, status=status.HTTP_200_OK)

            links = []
            try:
                resp = requests.get(
                    f"{base.rstrip('/')}/api/zil/entity-meta",
                    params={"plane_entity_id": cache_key},
                    headers={"X-Zil-Service-Key": secret},
                    timeout=5,
                )
                if resp.status_code == 200:
                    links = resp.json().get("links") or []
            except Exception as e:
                # Decorative chip: an ERP hiccup degrades to "no chip", never a 5xx.
                log_exception(e)

            if len(self._CACHE) >= self._CACHE_MAX:
                self._CACHE.clear()
            self._CACHE[cache_key] = (time.monotonic() + self._CACHE_TTL, links)
            return Response({"links": links}, status=status.HTTP_200_OK)
        except Exception as e:
            log_exception(e)
            return Response({"error": "erp_links_failed"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class ZilErpAssetRedirectEndpoint(APIView):
    """Open a Zil-stored document for a signed-in Plane user (302 to presigned).

    Per-user session auth — NOT the service key. Authorization: the requested
    key must belong to a doc-attach chip in a workspace the user is an active
    member of (so only deliberately attached docs are reachable, and only by
    that workspace's members). The presigned URL itself is fetched from Zil
    server-to-server; Zil's storage credentials never reach the browser.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        key = request.query_params.get("key")
        if not key:
            return Response({"error": "key required"}, status=status.HTTP_400_BAD_REQUEST)

        allowed = IssueLink.objects.filter(
            metadata__zil_key=key,
            workspace_id__in=WorkspaceMember.objects.filter(
                member=request.user, is_active=True
            ).values_list("workspace_id", flat=True),
        ).exists()
        if not allowed:
            return Response({"error": "not_found"}, status=status.HTTP_404_NOT_FOUND)

        base = os.environ.get("ZIL_BASE_URL")
        secret = os.environ.get("ZIL_SERVICE_SECRET")
        if not base or not secret:
            return Response({"error": "zil_not_configured"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        try:
            resp = requests.get(
                f"{base.rstrip('/')}/api/zil/asset-url",
                params={"key": key},
                headers={"X-Zil-Service-Key": secret},
                timeout=5,
            )
            if resp.status_code != 200:
                return Response({"error": "not_found"}, status=status.HTTP_404_NOT_FOUND)
            url = resp.json().get("url")
            if not url:
                return Response({"error": "not_found"}, status=status.HTTP_404_NOT_FOUND)
            return HttpResponseRedirect(url)
        except Exception as e:
            log_exception(e)
            return Response({"error": "zil_unreachable"}, status=status.HTTP_502_BAD_GATEWAY)


_ERP_REF_KINDS = ("client", "project")
# Every option at once: the dropdown filters locally, and a workspace's BUs hold tens of them.
_ERP_OPTIONS_LIMIT = 200


def _client_option(client):
    alias, company = client.get("alias") or "", client.get("companyName") or ""
    return {"id": client.get("id"), "name": alias or company, "subtitle": company if alias and company != alias else ""}


def _project_option(project):
    detail = " · ".join(filter(None, [project.get("clientName"), project.get("brand"), project.get("service")]))
    return {"id": project.get("id"), "name": project.get("name") or "", "subtitle": detail}


class ZilErpOptionsEndpoint(APIView):
    """Active ERP clients / projects of a workspace's Business Unit(s), for the
    work item "Cliente" / "Proyecto" properties. Per-user session auth: only
    active members of the workspace. Proxied from the ERP, never persisted.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        slug = request.query_params.get("workspace_slug")
        kind = request.query_params.get("kind")
        if kind not in _ERP_REF_KINDS or not slug:
            return Response({"error": "invalid_params"}, status=status.HTTP_400_BAD_REQUEST)
        if not WorkspaceMember.objects.filter(workspace__slug=slug, member=request.user, is_active=True).exists():
            return Response({"error": "not_found"}, status=status.HTTP_404_NOT_FOUND)
        if not zil_enabled():
            return Response({"error": "zil_not_configured"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        try:
            if kind == "client":
                options = [_client_option(c) for c in search_zil_clients(slug, "", _ERP_OPTIONS_LIMIT)]
            else:
                options = [_project_option(p) for p in search_zil_projects(slug, "", _ERP_OPTIONS_LIMIT)]
        except ZilUnavailable:
            return Response({"error": "zil_unavailable"}, status=status.HTTP_502_BAD_GATEWAY)
        return Response({"options": options}, status=status.HTTP_200_OK)


class ZilIssueErpRefsEndpoint(APIView):
    """The ERP client / project a work item belongs to.

    The link is owned by Zil Workspace (golden rule of the ERP↔Ops bridge): it
    lives in the client's / project's planeLinks[], and the ERP pushes the usual
    entity-link `set`/`clear` back (IssueLink chip + back-ref). This view only
    authorizes the requester against the work item's project and relays.

    GET  ?issue_id=               → {client, project} (each {id, name, url} or null)
    POST {issue_id, kind, erp_id} → link (erp_id) or unlink (erp_id=null); returns the new refs
    """

    permission_classes = [IsAuthenticated]

    def _issue(self, request, issue_id, min_role):
        try:
            uuid.UUID(str(issue_id))
        except ValueError:
            return None
        return (
            Issue.issue_objects.filter(
                pk=issue_id,
                project__project_projectmember__member=request.user,
                project__project_projectmember__is_active=True,
                project__project_projectmember__role__gte=min_role,
            )
            .select_related("workspace", "project")
            .first()
        )

    def get(self, request):
        issue = self._issue(request, request.query_params.get("issue_id"), min_role=5)
        if issue is None:
            return Response({"error": "not_found"}, status=status.HTTP_404_NOT_FOUND)
        if not zil_enabled():
            return Response({"client": None, "project": None}, status=status.HTTP_200_OK)
        try:
            return Response(get_issue_erp_refs(issue.workspace.slug, str(issue.id)), status=status.HTTP_200_OK)
        except ZilUnavailable:
            return Response({"error": "zil_unavailable"}, status=status.HTTP_502_BAD_GATEWAY)

    def post(self, request):
        kind = request.data.get("kind")
        erp_id = request.data.get("erp_id")
        if kind not in _ERP_REF_KINDS or (erp_id is not None and not is_valid_client_id(erp_id)):
            return Response({"error": "invalid_params"}, status=status.HTTP_400_BAD_REQUEST)
        # Editing a work item's properties needs Member or Admin on its project.
        issue = self._issue(request, request.data.get("issue_id"), min_role=15)
        if issue is None:
            return Response({"error": "not_found"}, status=status.HTTP_404_NOT_FOUND)
        if not zil_enabled():
            return Response({"error": "zil_not_configured"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        try:
            refs = set_issue_erp_ref(
                {
                    "kind": kind,
                    "erp_id": erp_id,
                    "workspace_slug": issue.workspace.slug,
                    "plane_issue_id": str(issue.id),
                    "actor_email": request.user.email,
                }
            )
        except ZilUnavailable:
            return Response({"error": "zil_unavailable"}, status=status.HTTP_502_BAD_GATEWAY)
        if refs is None:
            return Response({"error": "erp_entity_not_found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(refs, status=status.HTTP_200_OK)
