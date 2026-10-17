# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Plain dict views of the pipeline models, shared by the agent API and the in-app API."""

# Module imports
from plane.db.models import FileAsset
from plane.settings.storage import S3Storage
from plane.utils.agent_pipeline.bugs import classify_urgency


def _iso(value):
    return value.isoformat() if value else None


def _person(user):
    if user is None:
        return None
    return {
        "id": str(user.id),
        "email": user.email,
        "display_name": user.display_name,
        "first_name": user.first_name,
        "last_name": user.last_name,
    }


def attachments(asset_ids, request):
    if not asset_ids:
        return []
    assets = FileAsset.objects.filter(id__in=asset_ids, is_uploaded=True)
    storage = S3Storage(request=request)
    return [
        {
            "id": str(asset.id),
            "name": asset.attributes.get("name"),
            "type": asset.attributes.get("type"),
            "url": storage.generate_presigned_url(object_name=asset.asset.name),
        }
        for asset in assets
    ]


def bug_summary(bug):
    return {
        "id": str(bug.id),
        "status": bug.status,
        "severity": bug.severity,
        "source": bug.source,
        "origin": bug.origin,
        "urgency": classify_urgency(bug),
        "description": bug.description[:500],
        "url": bug.url,
        "display_title": bug.display_title,
        "category": bug.category,
        "plain_summary": bug.plain_summary,
        "occurrences": bug.occurrences,
        "affected_users": len(bug.affected_user_ids or []),
        "blocked_at": _iso(bug.blocked_at),
        "blocked_reason": bug.blocked_reason,
        "claimed_at": _iso(bug.claimed_at),
        "reported_by": _person(bug.reported_by),
        "workspace_slug": bug.workspace.slug if bug.workspace_id else None,
        "derived_feature_id": str(bug.derived_feature_id) if bug.derived_feature_id else None,
        # Where the suggestion it became stands: a derived report is done or stalled with it, not forever "in progress".
        "derived_feature_status": bug.derived_feature.status if bug.derived_feature_id else None,
        "workspace_bug_id": bug.workspace_bug_id or None,
        "workspace_bug_url": bug.workspace_bug_url or None,
        "resolved_message": bug.resolved_message,
        "created_at": _iso(bug.created_at),
        "last_seen_at": _iso(bug.last_seen_at),
        "fixed_at": _iso(bug.fixed_at),
        "resolved_at": _iso(bug.resolved_at),
    }


# Internal triage fields: admins and the agent see them, the person who reported does not.
REPORTER_HIDDEN = ("admin_notes", "commit_hash", "blocked_reason")


def _closed_as(data):
    """How an archived report had ended, for whoever reported it. Archiving is an admin tidying the
    queue, not an outcome: the email they got said resolved or answered, and the answer is kept."""
    if not data.get("resolved_at"):
        return "archived"  # archived before anyone closed it: it really didn't advance
    if data.get("derived_feature_id") or data.get("workspace_bug_id"):
        return "dismissed"
    if data.get("resolved_message") and not (data.get("fixed_at") or data.get("commit_hash")):
        return "dismissed"  # answered: nothing in the platform changed
    return "resolved"


def for_reporter(data):
    shown = {key: value for key, value in data.items() if key not in REPORTER_HIDDEN}
    if shown.get("status") == "archived":
        shown["status"] = _closed_as(data)
    return shown


def bug_detail(bug, request):
    return {
        **bug_summary(bug),
        "description": bug.description,
        "user_agent": bug.user_agent,
        "viewport": bug.viewport,
        "system_info": bug.system_info,
        "console_logs": bug.console_logs,
        "error_type": bug.error_type,
        "stack_trace": bug.stack_trace,
        "fingerprint": bug.fingerprint,
        "attachments": attachments(bug.attachment_ids, request),
        "progress": bug.progress,
        "comments": bug.comments,
        "admin_notes": bug.admin_notes,
        "commit_hash": bug.commit_hash,
    }


def _answered(feature):
    """needs_info whose last agent question already has the requester's answer after it: the analysis
    didn't relaunch (feature agent off), so it now waits on an admin, not on the requester."""
    if feature.status != "needs_info":
        return False
    comments = feature.comments or []
    last_question = max((i for i, c in enumerate(comments) if c.get("role") == "agent"), default=-1)
    return last_question >= 0 and any(c.get("role") == "user" for c in comments[last_question + 1 :])


def feature_summary(feature):
    spec = feature.spec or {}
    build = feature.build or {}
    return {
        "id": str(feature.id),
        "status": feature.status,
        "title": feature.title,
        "display_title": feature.display_title,
        "category": feature.category,
        "plain_summary": feature.plain_summary,
        "priority": feature.priority,
        "blast_radius": spec.get("blast_radius"),
        "flag_key": feature.flag_key,
        "requested_by": _person(feature.requested_by),
        "workspace_slug": feature.workspace.slug if feature.workspace_id else None,
        "pr_url": build.get("pr_url"),
        "build_blocked": bool(build.get("blocked_at")),
        "answered": _answered(feature),
        "created_at": _iso(feature.created_at),
        "updated_at": _iso(feature.updated_at),
    }


def feature_detail(feature, request):
    return {
        **feature_summary(feature),
        "problem": feature.problem,
        "desired_outcome": feature.desired_outcome,
        "source_url": feature.source_url,
        "attachments": attachments(feature.attachment_ids, request),
        "spec": feature.spec,
        "spec_runs": feature.spec_runs,
        "approval": feature.approval,
        "rejection": feature.rejection,
        "build": feature.build,
        "comments": feature.comments,
    }
