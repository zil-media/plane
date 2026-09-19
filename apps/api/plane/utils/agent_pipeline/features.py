# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
from datetime import timedelta

# Django imports
from django.utils import timezone

# Module imports
from plane.db.models import AgentPipelineConfig, FeatureRequest

from .constants import MAX_SPEC_RUNS

S = FeatureRequest.Status

# One build in flight at a time: two sessions on overlapping files make conflicting branches.
BUILD_ACTIVE = (S.BUILDING,)


def request_spec(feature, reason, force=False):
    """Queues an impact assessment. Returns (queued, reason)."""
    config = AgentPipelineConfig.get()
    if not config.feature_agent_enabled:
        return False, "disabled"
    if feature.status in (S.SPEC_RUNNING, S.BUILDING, S.MERGED, S.REJECTED) and not force:
        return False, f"status {feature.status}"
    if feature.spec_runs >= MAX_SPEC_RUNS and not force:
        return False, "spec run limit"

    from plane.bgtasks.agent_pipeline_task import fire_feature_routine_task

    feature.status = S.SPEC_RUNNING
    feature.spec_runs += 1
    feature.spec_requested_at = timezone.now()
    feature.save(update_fields=["status", "spec_runs", "spec_requested_at", "updated_at"])
    fire_feature_routine_task.delay(str(feature.id), "SPEC", reason)
    return True, "queued"


def builds_this_week():
    since = (timezone.now() - timedelta(days=7)).isoformat()
    return sum(
        1
        for claimed in FeatureRequest.objects.filter(build__claimed_at__isnull=False).values_list(
            "build__claimed_at", flat=True
        )
        if claimed and claimed >= since
    )


def request_build(feature, reason="aprobada"):
    """Dispatches the BUILD session for an approved feature, if the lane has room. Returns (fired, reason)."""
    config = AgentPipelineConfig.get()
    if not config.feature_agent_enabled:
        return False, "disabled"
    if feature.status != S.APPROVED:
        return False, f"status {feature.status}"
    if FeatureRequest.objects.filter(status__in=BUILD_ACTIVE).exclude(id=feature.id).exists():
        return False, "another build in flight"
    if builds_this_week() >= config.max_builds_per_week:
        return False, f"tope semanal de {config.max_builds_per_week} builds alcanzado"

    from plane.bgtasks.agent_pipeline_task import fire_feature_routine_task

    build = dict(feature.build or {})
    build.update(
        {
            "claimed_at": timezone.now().isoformat(),
            "runs": int(build.get("runs", 0)) + 1,
            "branch": f"feat/agent/{feature.id}",
            "blocked_at": None,
        }
    )
    feature.build = build
    feature.status = S.BUILDING
    feature.save(update_fields=["build", "status", "updated_at"])
    fire_feature_routine_task.delay(str(feature.id), "BUILD", reason)
    return True, "queued"


def drain_feature_queue(reason="se liberó la corrida anterior"):
    """Starts the oldest approved build once the lane is free."""
    next_feature = FeatureRequest.objects.filter(status=S.APPROVED).order_by("updated_at").first()
    if next_feature is None:
        return False, "empty"
    return request_build(next_feature, reason)
