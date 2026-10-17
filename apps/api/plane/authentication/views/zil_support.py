# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Service-key read of the support board, for Zil Workspace's "Seguimiento".

Ops stays the source of truth for its own suggestions: Workspace reads this on every board load
and never stores a copy, so there is nothing to keep in sync. Decisions and answers still happen
here — every item carries the link back to the Ops board.
"""

# Django imports
from django.db.models import Q

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.agent_api.serialize import bug_summary, feature_summary, for_reporter
from plane.authentication.views.zil_sync import ZilServiceView
from plane.db.models import AgentFeatureFlag, BugReport, FeatureRequest, User, WorkspaceMember
from plane.utils.agent_pipeline.notify import support_url
from plane.utils.agent_pipeline.permissions import is_instance_admin
from plane.utils.exception_logger import log_exception

S = FeatureRequest.Status


def _comment(entry):
    return {
        "author_name": entry.get("author_name", ""),
        "role": entry.get("role", "user"),
        "text": entry.get("text", ""),
        "at": entry.get("at"),
    }


def _feature(feature, url, flag_enabled_at):
    spec = feature.spec or {}
    build = feature.build or {}
    approval = feature.approval or {}
    rejection = feature.rejection or {}
    return {
        **feature_summary(feature),
        "problem": feature.problem,
        "desired_outcome": feature.desired_outcome,
        "spec": {
            "summary": spec.get("summary", ""),
            "blast_radius": spec.get("blast_radius", ""),
            "generated_at": spec.get("generated_at"),
        },
        "approval": {
            "auto": approval.get("by") == "auto",
            "by_name": approval.get("by_name", ""),
            "at": approval.get("at"),
        },
        "rejection": {
            "by_name": rejection.get("by_name", ""),
            "at": rejection.get("at"),
            "notes": rejection.get("notes", ""),
        },
        "build": {
            "claimed_at": build.get("claimed_at"),
            "blocked_at": build.get("blocked_at"),
            "merged_at": build.get("merged_at"),
            "pr_url": build.get("pr_url", ""),
            # Why a build stopped or was paused, in words meant for the requester (it's also mailed to them).
            "last_note": build.get("last_note", ""),
            "progress": build.get("progress") or [],
        },
        "comments": [_comment(c) for c in feature.comments or []],
        "flag_enabled_at": flag_enabled_at,
        "url": url,
    }


def _bug(bug, url):
    return {
        # Progress goes through for_reporter too: a step's for_agent (CI's run link) isn't the person's.
        **for_reporter({**bug_summary(bug), "progress": bug.progress or []}),
        # bug_summary cuts the text at 500 for the admin lists; the person's own report goes whole.
        "description": bug.description,
        "comments": [_comment(c) for c in bug.comments or []],
        "updated_at": bug.updated_at.isoformat() if bug.updated_at else None,
        "url": url,
    }


class ZilSupportTrackingEndpoint(ZilServiceView):
    """One person's suggestions in Ops, for Zil Workspace's tracking board. Read-only.

    GET ?email=<email> → {is_admin, features, bugs}.
    - features: the person's own suggestions; for an instance admin (the only ones who decide
      here) also the ones waiting on an admin: spec ready, or a stuck build (status "building"
      with build.blocked_at: the agent reported it blocked and nobody resumes it alone).
    - bugs: the person's own manual reports (Workspace's Seguimiento shows your own bugs too). Reports
      already handed to Workspace are left out: that report lives in Workspace and shows there on its own.
    An email with no active Ops user answers empty lists, not an error: not everyone uses Ops.
    """

    _MAX_FEATURES = 200
    _MAX_BUGS = 100
    # Service-key calls have no session, so DRF's default anon throttle (30/min per caller IP)
    # would bucket every Workspace board poll together and answer 429 to the whole team.
    throttle_classes = []

    def get(self, request):
        email = (request.query_params.get("email") or "").strip().lower()
        if not email or "@" not in email or len(email) > 254:
            return Response({"error": "invalid_email"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            user = User.objects.filter(email__iexact=email, is_active=True).first()
            if user is None:
                return Response({"is_admin": False, "features": [], "bugs": []}, status=status.HTTP_200_OK)

            is_admin = is_instance_admin(user)
            # Items with no workspace, or one the viewer isn't in (an admin looking at someone else's
            # suggestion), still open on the board, which is instance-wide: any workspace of the
            # viewer's serves as the door. A link to a workspace they're not in answers "not found".
            memberships = list(
                WorkspaceMember.objects.filter(member=user, is_active=True, deleted_at__isnull=True)
                .select_related("workspace")
                .order_by("created_at")
            )
            member_of = {m.workspace_id for m in memberships}
            fallback = memberships[0].workspace if memberships else None

            def door(item):
                return item.workspace if item.workspace_id in member_of else fallback

            scope = Q(requested_by=user)
            if is_admin:
                scope |= Q(status__in=(S.SPEC_READY, S.BUILDING, S.NEEDS_INFO))
            candidates = FeatureRequest.objects.filter(scope).select_related("requested_by", "workspace")
            features = [
                f
                for f in candidates[: self._MAX_FEATURES]
                if f.requested_by_id == user.id
                or f.status == S.SPEC_READY
                or (f.status == S.BUILDING and (f.build or {}).get("blocked_at"))
                # Answered and nothing relaunched it: an admin's to restart, like Ops's own board says.
                or (f.status == S.NEEDS_INFO and feature_summary(f)["answered"])
            ]
            flag_keys = [f.flag_key for f in features if f.flag_key]
            enabled = dict(
                AgentFeatureFlag.objects.filter(key__in=flag_keys, enabled=True).values_list("key", "enabled_at")
            )

            bugs = (
                BugReport.objects.filter(reported_by=user, source=BugReport.Source.MANUAL)
                .exclude(status=BugReport.Status.ARCHIVED)
                # Handed to Workspace AND closed here: that report lives in Workspace. One handed over
                # but still open here (part of the fix is Ops's) keeps showing.
                .exclude(~Q(workspace_bug_id=""), status=BugReport.Status.DISMISSED)
                .select_related("reported_by", "workspace", "derived_feature")[: self._MAX_BUGS]
            )

            return Response(
                {
                    "is_admin": is_admin,
                    "features": [
                        _feature(
                            f,
                            support_url(door(f), f.id, "feature"),
                            enabled[f.flag_key].isoformat() if enabled.get(f.flag_key) else None,
                        )
                        for f in features
                    ],
                    "bugs": [_bug(b, support_url(door(b), b.id, "bug")) for b in bugs],
                },
                status=status.HTTP_200_OK,
            )
        except Exception as e:
            log_exception(e)
            return Response({"error": "support_tracking_failed"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
