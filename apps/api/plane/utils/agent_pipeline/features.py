# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
from datetime import timedelta

# Django imports
from django.db import transaction
from django.utils import timezone

# Module imports
from plane.db.models import AgentPipelineConfig, FeatureRequest

from .constants import MAX_BUILD_RUNS, MAX_SPEC_RUNS

S = FeatureRequest.Status

# One build in flight at a time: two sessions on overlapping files make conflicting branches.
BUILD_ACTIVE = (S.BUILDING,)

# An analysis only (re)starts before anything was built or decided for good. Not from spec_running
# (a second run of the same spec), approved/building/in_review/queued (it would pull the item off
# its build and free the build slot) or merged/rejected (it would undo the decision).
SPEC_STARTABLE = (S.SUBMITTED, S.NEEDS_INFO, S.SPEC_READY, S.ON_HOLD)


def request_spec(feature, reason, force=False):
    """Queues an impact assessment. Returns (queued, reason).

    `force` only lifts the automatic-run cap (a person asked for it); it never skips the status
    check. The row is re-read under a lock: the caller's copy can be stale (an admin decided, or
    another request already started a run, between the caller's read and this one).
    """
    config = AgentPipelineConfig.get()
    if not config.feature_agent_enabled:
        return False, "disabled"

    from plane.bgtasks.agent_pipeline_task import fire_feature_routine_task

    with transaction.atomic():
        current = FeatureRequest.objects.select_for_update().get(id=feature.id)
        if current.status not in SPEC_STARTABLE:
            return False, f"status {current.status}"
        if current.spec_runs >= MAX_SPEC_RUNS and not force:
            return False, "spec run limit"
        current.status = S.SPEC_RUNNING
        current.spec_runs += 1
        current.spec_requested_at = timezone.now()
        current.save(update_fields=["status", "spec_runs", "spec_requested_at", "updated_at"])
    feature.status, feature.spec_runs, feature.spec_requested_at = (
        current.status,
        current.spec_runs,
        current.spec_requested_at,
    )
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


def lane_busy(exclude_id=None):
    """A build session is actually running. A blocked build (build.blocked_at) ended its session and
    waits for a person: it doesn't hold the lane, or one stuck item would starve every approved one."""
    running = FeatureRequest.objects.filter(status__in=BUILD_ACTIVE).exclude(id=exclude_id)
    return any(not (f.build or {}).get("blocked_at") for f in running.only("id", "build"))


def request_build(feature, reason="aprobada"):
    """Dispatches the BUILD session for an approved feature, if the lane has room. Returns (fired, reason).

    One dispatcher at a time: the config row is locked as a mutex, because the in-flight check spans
    rows (the drain and an admin's approve could both see a free lane and fire two sessions). The
    feature row is re-read under that lock; the caller's copy is updated with what was saved.
    """
    from plane.bgtasks.agent_pipeline_task import fire_feature_routine_task

    with transaction.atomic():
        config = AgentPipelineConfig.objects.select_for_update().get(pk=AgentPipelineConfig.get().pk)
        if not config.feature_agent_enabled:
            return False, "disabled"
        current = FeatureRequest.objects.select_for_update().get(id=feature.id)
        if current.status != S.APPROVED:
            return False, f"status {current.status}"
        if lane_busy(exclude_id=current.id):
            return False, "another build in flight"
        if builds_this_week() >= config.max_builds_per_week:
            return False, f"tope semanal de {config.max_builds_per_week} builds alcanzado"

        build = dict(current.build or {})
        runs = int(build.get("runs", 0))
        if runs >= MAX_BUILD_RUNS and not build.get("manual_retry"):
            # Out of the approved queue, not just skipped: the drain only ever tries the oldest approved
            # feature, so one stuck here would starve every build behind it.
            build["last_note"] = (
                f"La construcción se intentó {runs} veces sin terminar. Queda en espera hasta que el equipo la revise."
            )
            current.build = build
            current.status = S.ON_HOLD
            current.save(update_fields=["build", "status", "updated_at"])
            feature.build, feature.status = current.build, current.status
            return False, "build run limit"

        build.update(
            {
                "claimed_at": timezone.now().isoformat(),
                "runs": runs + 1,
                "branch": f"feat/agent/{current.id}",
                "blocked_at": None,
                # A new run: the previous run's note and progress would read as this one's.
                "last_note": "",
                "progress": [],
                # A person's rebuild buys exactly one run; the sweep's re-fires count against the cap again.
                "manual_retry": False,
            }
        )
        current.build = build
        current.status = S.BUILDING
        current.save(update_fields=["build", "status", "updated_at"])
    feature.build, feature.status = current.build, current.status
    fire_feature_routine_task.delay(str(feature.id), "BUILD", reason)
    return True, "queued"


def drain_feature_queue(reason="se liberó la corrida anterior"):
    """Starts the oldest approved build once the lane is free."""
    next_feature = FeatureRequest.objects.filter(status=S.APPROVED).order_by("updated_at").first()
    if next_feature is None:
        return False, "empty"
    return request_build(next_feature, reason)
