# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
Zil Workspace → Plane provisioning.

Zil Workspace is the source of truth for identity, Business Units and access.
This module materializes that state in Plane:

  * a Zil Business Unit  ->  a Plane Workspace (slug == BU slug, immutable)
  * a user's BU list     ->  that user's WorkspaceMember rows (with mapped role)
  * a director of a BU   ->  owner of the corresponding Workspace

Two entry points use the same core:
  * JIT at login (ZilSSOEndpoint) — the desired workspace list rides in the
    signed SSO token, so no callback to Zil is needed.
  * event-driven / reconcile sync API (zil_sync views) — Zil pushes changes.

All operations are idempotent so they are safe to run on every login and on
every sync call.
"""

# Python imports
import os
import uuid
import logging

# Django imports
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.text import slugify

# Third party imports
import requests

# Module imports
from plane.db.models import User, Workspace, WorkspaceMember, Profile
from plane.utils.color import get_random_color
from plane.utils.constants import RESTRICTED_WORKSPACE_SLUGS
from plane.utils.exception_logger import log_exception

logger = logging.getLogger("plane.authentication")

# Service identity that owns workspaces created by sync before their real
# director has logged in. Ownership is transferred to the director on their
# first login (see _sync_membership). is_bot=True keeps it out of member
# counts and blocks interactive login of this account.
ZIL_SERVICE_EMAIL = "zil-service@zil.internal"

# Zil role -> Plane WorkspaceMember role int. Admin(20) / Member(15) / Guest(5).
# Locked decisions: admin & director => Admin(20); hr & operativo => Member(15);
# guest => Guest(5). Admins additionally receive a membership in EVERY workspace,
# but that breadth is decided on the Zil side (it sends the full workspace list);
# Plane just materializes whatever list it is handed.
_ROLE_MAP = {"admin": 20, "director": 20, "hr": 15, "operativo": 15, "guest": 5}
_DEFAULT_ROLE = 15

# Default UI language for provisioned users (the company works in Spanish).
ZIL_DEFAULT_LANGUAGE = "es"


def map_role(zil_role):
    """Map a Zil role string to a Plane WorkspaceMember role int.

    Defensive: coerces non-strings so an unexpected type never raises.
    """
    return _ROLE_MAP.get(str(zil_role or "").strip().lower(), _DEFAULT_ROLE)


def normalize_slug(slug):
    """Plane workspace slugs are max 48 chars, slugified, unique.

    Also guards against a Business Unit name (e.g. "Billing", "Settings",
    "Admin") slugifying into a reserved app route — that would let a
    workspace shadow e.g. /billing or /settings. Mirrors the
    RESTRICTED_WORKSPACE_SLUGS check in app/serializers/workspace.py, but
    since this path has no form to surface a validation error to, it
    disambiguates instead of rejecting.
    """
    normalized = slugify(str(slug or ""))[:48]
    attempts = 0
    while normalized and normalized in RESTRICTED_WORKSPACE_SLUGS and attempts < 5:
        normalized = f"{normalized}-ws"[:48]
        attempts += 1
    return normalized


def get_service_user():
    """Return (creating if needed) the Zil service/bot user used as the
    fallback owner for freshly-synced workspaces.

    Concurrency-safe: two simultaneous first-logins would otherwise both pass
    the existence check and race to INSERT the same unique email. We let one
    win and re-fetch on the resulting IntegrityError instead of surfacing a 500.
    """
    user = User.objects.filter(email=ZIL_SERVICE_EMAIL).first()
    if user:
        return user
    try:
        return User.objects.create(
            email=ZIL_SERVICE_EMAIL,
            username=uuid.uuid4().hex,
            display_name="Zil Service",
            is_bot=True,
            is_password_autoset=True,
            is_email_verified=True,
            is_active=True,
        )
    except IntegrityError:
        # Lost the race — the row now exists; return it.
        return User.objects.filter(email=ZIL_SERVICE_EMAIL).first()


def ensure_workspace(slug, name=None, color=None, logo_url=None, owner=None):
    """Idempotently create-or-update a Workspace for a Business Unit.

    The slug is immutable once created (it is the workspace URL). name / color /
    logo are synced on every call. Returns (workspace, created).
    """
    slug = normalize_slug(slug)
    if not slug:
        raise ValueError("empty workspace slug")

    ws = Workspace.objects.filter(slug=slug).first()
    if ws:
        update_fields = []
        if name and ws.name != name[:80]:
            ws.name = name[:80]
            update_fields.append("name")
        if color and ws.background_color != color:
            ws.background_color = color
            update_fields.append("background_color")
        if logo_url and ws.logo != logo_url:
            ws.logo = logo_url
            update_fields.append("logo")
        if update_fields:
            ws.save(update_fields=update_fields)
        return ws, False

    owner = owner or get_service_user()
    try:
        ws = Workspace.objects.create(
            name=(name or slug)[:80],
            slug=slug,
            owner=owner,
            background_color=color or get_random_color(),
            logo=logo_url or None,
        )
    except IntegrityError:
        # Concurrent sync/login created the same slug first. Return the existing
        # workspace (same inputs → equivalent state) instead of 500ing.
        existing = Workspace.objects.filter(slug=slug).first()
        if existing:
            return existing, False
        raise
    # Seed default issue states / labels / etc. so the workspace is usable.
    # Imported lazily to avoid a hard dependency on the celery app at import time.
    try:
        from plane.bgtasks.workspace_seed_task import workspace_seed

        workspace_seed.delay(str(ws.id))
    except Exception as e:
        log_exception(e)
    return ws, True


def _upsert_membership(workspace, user, role, authoritative=False):
    """Ensure `user` is an active WorkspaceMember of `workspace` with `role`.

    Concurrency-safe: a lost create race (two provisions of the same user, e.g.
    a double-click SSO) re-fetches and updates instead of raising IntegrityError.

    Reactivation guard: Plane has no persisted Workspace.is_active /
    deactivated_at field, so a BU deactivated via deactivate_workspace() is
    only durably reflected by *every* WorkspaceMember row on that workspace
    being is_active=False. We use "zero active members" as the proxy for
    "this workspace was deactivated" and only lift it when `authoritative`
    is True — i.e. the incoming sync is Zil's confirmed current state and
    explicitly re-includes this workspace/user (see provision_user_workspaces'
    docstring). A non-authoritative call (JIT SSO token, best-effort sync)
    must not silently undo a revocation.
    """
    wm = WorkspaceMember.objects.filter(workspace=workspace, member=user).first()
    if not wm:
        try:
            return WorkspaceMember.objects.create(workspace=workspace, member=user, role=role)
        except IntegrityError:
            wm = WorkspaceMember.objects.filter(workspace=workspace, member=user).first()
            if not wm:
                raise
    update_fields = []
    if wm.role != role:
        wm.role = role
        update_fields.append("role")
    if not wm.is_active:
        workspace_deactivated = not WorkspaceMember.objects.filter(
            workspace=workspace, is_active=True
        ).exists()
        if workspace_deactivated and not authoritative:
            logger.warning(
                "Zil provisioning: refusing to reactivate membership for %s in "
                "workspace %s — workspace appears deactivated (no active "
                "members) and this sync is not authoritative",
                getattr(user, "email", user.pk),
                workspace.slug,
            )
        else:
            wm.is_active = True
            update_fields.append("is_active")
    if update_fields:
        wm.save(update_fields=update_fields)
    return wm


def provision_user_workspaces(user, workspaces, authoritative=False):
    """Reconcile a user's workspace memberships against the desired list.

    `workspaces` is a list of dicts:
        {slug, name, color, logo_url, role, is_owner}
    where `role` is either a Plane int (5/15/20) or a Zil role string.

    `authoritative` says whether the list is Zil's *confirmed* full desired
    state. When True, memberships NOT in the list are deactivated. When False
    (the default — e.g. Zil's workspace computation failed and we only have an
    empty/partial list), existing access is left untouched so a transient error
    can never silently wipe a user's workspaces.

    Safety guard: an authoritative-but-EMPTY list never revokes anything. An
    empty desired list is almost always a truncated/partial payload (a Zil
    compute glitch or a dropped list), not a genuine "removed from every BU".
    Revoking on it wipes a live user's access mid-session, so we refuse it —
    real full-deprovision is explicit elsewhere (suspended → deactivate_user,
    BU deactivated → deactivate_workspace).

    - creates/updates the Workspace for each BU
    - adds/updates the user's membership with the mapped role
    - transfers ownership to the user when they are the BU director and the
      workspace is still owned by the service account
    - deactivates memberships not in the desired list (only if authoritative)
    - marks the profile onboarded and points last_workspace at the primary one
      so the user skips onboarding and lands inside a workspace

    Returns the primary Workspace (first in the list) or None.
    """
    workspaces = workspaces or []
    service = get_service_user()
    primary = None
    desired_ws_ids = set()

    for entry in workspaces:
        try:
            slug = normalize_slug(entry.get("slug"))
            if not slug:
                logger.warning(
                    "Zil provisioning: BU slug %r normalized to empty (non-ASCII?); workspace skipped",
                    entry.get("slug"),
                )
                continue
            # Validate the role. Trust a Plane int only if it's a real role
            # (5/15/20); an unknown int (e.g. 999) falls back to the default,
            # and a Zil role string is mapped.
            raw_role = entry.get("role")
            if isinstance(raw_role, int):
                role = raw_role if raw_role in _ROLE_MAP.values() else _DEFAULT_ROLE
            else:
                role = map_role(raw_role)
            is_owner = bool(entry.get("is_owner"))

            # Create the workspace directly owned by the user when they are the
            # director (avoids the bot-owner + transfer dance on first touch).
            create_owner = user if is_owner else service
            # Atomic per entry: if membership creation fails we must not leave a
            # workspace created-but-memberless (orphan owned by the bot/user).
            with transaction.atomic():
                ws, _created = ensure_workspace(
                    slug=slug,
                    name=entry.get("name"),
                    color=entry.get("color"),
                    logo_url=entry.get("logo_url"),
                    owner=create_owner,
                )
                _upsert_membership(ws, user, role, authoritative=authoritative)

                # Transfer ownership to the director if the workspace is still
                # owned by the service account.
                if is_owner and ws.owner_id == service.id:
                    ws.owner = user
                    ws.save(update_fields=["owner"])

            desired_ws_ids.add(ws.id)
            if primary is None:
                primary = ws
        except Exception as e:
            log_exception(e)
            continue

    # Deactivate memberships for workspaces the user should no longer be in
    # (BU removed on the Zil side). Only when the list is authoritative — a
    # non-authoritative (or empty) list means "unknown/partial" and must NOT
    # wipe access.
    if authoritative and not desired_ws_ids:
        # Authoritative but empty ⇒ almost certainly a truncated/partial payload.
        # Refuse to revoke-all; leave existing access intact. (See docstring.)
        logger.warning(
            "Zil provisioning: authoritative but EMPTY desired workspace list "
            "for user %s — refusing to revoke memberships (treated as partial payload)",
            getattr(user, "email", user.pk),
        )
    if authoritative and desired_ws_ids:
        WorkspaceMember.objects.filter(member=user, is_active=True).exclude(
            workspace_id__in=desired_ws_ids
        ).update(is_active=False)

        # Hand off ownership of any workspace this user owns but no longer has an
        # active membership in (a director who left the BU). Give it to another
        # active human member (highest role first), else back to the service bot,
        # so no workspace is left owned by an inactive member.
        active_ws_ids = WorkspaceMember.objects.filter(member=user, is_active=True).values("workspace_id")
        orphaned = Workspace.objects.filter(owner=user).exclude(id__in=active_ws_ids)
        for ws in orphaned:
            replacement = (
                WorkspaceMember.objects.filter(workspace=ws, is_active=True, member__is_bot=False)
                .exclude(member=user)
                .order_by("-role")
                .select_related("member")
                .first()
            )
            ws.owner = replacement.member if replacement else service
            ws.save(update_fields=["owner"])

    # Skip onboarding, default to Spanish, and land the user inside their
    # primary workspace. Only mark onboarded if we actually provisioned a
    # workspace — otherwise leave the user in Plane's onboarding rather than
    # stranding them "onboarded" with no workspace.
    profile, _ = Profile.objects.get_or_create(user=user)
    update_fields = []
    if primary and not profile.is_onboarded:
        profile.is_onboarded = True
        update_fields.append("is_onboarded")
    if profile.language != ZIL_DEFAULT_LANGUAGE:
        profile.language = ZIL_DEFAULT_LANGUAGE
        update_fields.append("language")
    if primary and profile.last_workspace_id != primary.id:
        profile.last_workspace_id = primary.id
        update_fields.append("last_workspace_id")
    if update_fields:
        profile.save(update_fields=update_fields)

    return primary


def provision_user_from_zil(user, request=None):
    """Fetch a user's desired workspaces from Zil and provision them.

    Used for login paths that carry no signed workspace list (Google OAuth,
    magic link, email/password) so those users also land in their BU
    workspaces. Requires ZIL_BASE_URL + ZIL_SERVICE_SECRET; a no-op otherwise.
    Best-effort: never raises to the caller.
    """
    base = os.environ.get("ZIL_BASE_URL")
    secret = os.environ.get("ZIL_SERVICE_SECRET")
    if not base or not secret or not getattr(user, "email", None):
        return None
    try:
        resp = requests.get(
            f"{base.rstrip('/')}/api/sso/provision-context",
            params={"email": user.email},
            headers={"X-Zil-Service-Key": secret},
            # Short timeout: this is a best-effort side-effect on the login hot
            # path (Google/magic/email). If Zil is slow/down the user must not
            # wait — provisioning falls back to their next login / a reconcile.
            timeout=3,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
    except Exception as e:
        log_exception(e)
        return None

    if data.get("suspended"):
        return deactivate_user(user.email)
    # provision-context always reflects Zil's computed state (200 with the
    # user's current BUs), so it is authoritative.
    return provision_user_workspaces(
        user, data.get("workspaces") or [], authoritative=bool(data.get("authoritative"))
    )


def deactivate_workspace(slug):
    """Revoke access to a workspace whose Business Unit was deactivated in Zil.

    The workspace itself is kept (its slug is a permanent URL) but every
    membership is deactivated, so no one can reach it until the BU is
    reactivated (which re-provisions members on their next login/sync).
    """
    slug = normalize_slug(slug)
    if not slug:
        return None
    ws = Workspace.objects.filter(slug=slug).first()
    if not ws:
        return None
    WorkspaceMember.objects.filter(workspace=ws, is_active=True).update(is_active=False)
    return ws


def deactivate_user(email):
    """Deprovision: deactivate all memberships and block future login.

    Setting last_logout_time makes complete_login_or_signup reject the account
    with USER_ACCOUNT_DEACTIVATED on any subsequent SSO attempt.
    """
    user = User.objects.filter(email=str(email).strip().lower()).first()
    if not user:
        return None
    WorkspaceMember.objects.filter(member=user).update(is_active=False)
    user.is_active = False
    user.last_logout_time = timezone.now()
    user.save(update_fields=["is_active", "last_logout_time"])
    return user
