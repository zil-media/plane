# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
import hashlib

# Django imports
from django.db import transaction
from django.utils import timezone

# Module imports
from plane.db.models import BugReport, FeatureRequest

from .constants import ESCALATE_EVERY, ESCALATE_MIN_GAP, NOISE_PATTERNS

ACTIVE_STATUSES = (BugReport.Status.OPEN, BugReport.Status.IN_PROGRESS, BugReport.Status.FIXED)


def agent_queue():
    return BugReport.objects.filter(status=BugReport.Status.OPEN, blocked_at__isnull=True)


def fingerprint_for(key):
    return hashlib.sha1(key.encode("utf-8", "replace")).hexdigest()[:16]


def classify_urgency(bug):
    """noise | low | medium | high | urgent. Computed, never stored."""
    desc = (bug.description or "").lower()
    stack = (bug.stack_trace or "").lower()
    occurrences = bug.occurrences or 1
    users = len(bug.affected_user_ids or [])

    if any(p in desc or p in stack for p in NOISE_PATTERNS):
        return "noise"
    if "chunkloaderror" in desc or "failed to fetch dynamically" in desc:
        return "low"
    if "failed to fetch" in desc and occurrences <= 2 and users <= 1:
        return "low"
    if occurrences >= 10 or users >= 3:
        return "urgent"
    if occurrences >= 5 or users >= 2:
        return "high"
    if bug.severity == BugReport.Severity.BLOQUEANTE:
        return "high"
    if bug.severity == BugReport.Severity.SUGERENCIA:
        return "low"
    return "medium"


def trigger_urgency_for_new(bug):
    if bug.severity == BugReport.Severity.BLOQUEANTE:
        return "high"
    return "manual" if bug.source == BugReport.Source.MANUAL else "new"


def file_auto_bug_report(
    *,
    key,
    description,
    error_type="",
    url="",
    origin="",
    stack_trace="",
    system_info=None,
    console_logs=None,
    user=None,
    workspace=None,
):
    """Creates an auto report, or bumps the active one with the same fingerprint.

    Returns (bug, escalate): `escalate` says whether this occurrence should fire the agent —
    on create, then every ESCALATE_EVERY occurrences, at most once per ESCALATE_MIN_GAP.
    """
    fingerprint = fingerprint_for(key)
    now = timezone.now()
    user_id = str(user.id) if user else None

    with transaction.atomic():
        bug = (
            BugReport.objects.select_for_update()
            .filter(fingerprint=fingerprint, status__in=ACTIVE_STATUSES)
            .order_by("-created_at")
            .first()
        )
        if bug is None:
            bug = BugReport.objects.create(
                reported_by=user,
                workspace=workspace,
                description=description[:5000],
                source=BugReport.Source.AUTO,
                origin=origin[:30],
                fingerprint=fingerprint,
                error_type=error_type[:255],
                url=url[:2000],
                stack_trace=stack_trace[:20000],
                system_info=system_info or {},
                console_logs=(console_logs or [])[-30:],
                affected_user_ids=[user_id] if user_id else [],
                last_seen_at=now,
                last_escalated_at=now,
            )
            return bug, True

        bug.occurrences += 1
        bug.last_seen_at = now
        if user_id and user_id not in bug.affected_user_ids:
            bug.affected_user_ids = [*bug.affected_user_ids, user_id]
        escalate = bug.occurrences % ESCALATE_EVERY == 0 and (
            bug.last_escalated_at is None or now - bug.last_escalated_at >= ESCALATE_MIN_GAP
        )
        if escalate:
            bug.last_escalated_at = now
        bug.save(update_fields=["occurrences", "last_seen_at", "affected_user_ids", "last_escalated_at", "updated_at"])
        return bug, escalate


def append_entry(items, entry, limit=200):
    return [*(items or []), entry][-limit:]


def progress_entry(phase, note=""):
    return {"at": timezone.now().isoformat(), "phase": phase, "note": (note or "")[:500]}


def comment_entry(user, role, text):
    return {
        "at": timezone.now().isoformat(),
        "author_id": str(user.id) if user else None,
        "author_name": (user.display_name or user.first_name or user.email) if user else "",
        "role": role,
        "text": text[:5000],
    }


def derive_feature(bug, *, title, problem, desired_outcome, message, agent_user):
    """Turns a bug that is really a feature request into a suggestion filed in the reporter's name."""
    with transaction.atomic():
        feature = FeatureRequest.objects.create(
            requested_by=bug.reported_by or agent_user,
            workspace=bug.workspace,
            title=title[:200],
            problem=problem,
            desired_outcome=desired_outcome or "",
            source_url=bug.url,
        )
        bug.status = BugReport.Status.DISMISSED
        bug.derived_feature = feature
        bug.resolved_message = message
        bug.resolved_at = timezone.now()
        bug.claimed_at = None
        bug.save()
    return feature
