# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""/api/agent/bugs/* — the bug-fix agent's queue, and the CI lane's bookkeeping."""

# Django imports
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone

# Third party imports
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

# Module imports
from plane.db.models import BugReport
from plane.utils.agent_pipeline import bugs as bug_ops
from plane.utils.agent_pipeline import features as feature_ops
from plane.utils.agent_pipeline import notify
from plane.utils.agent_pipeline.constants import (
    BUG_PROGRESS_PHASES,
    DISPLAY_TITLE_MAX,
    PLAIN_SUMMARY_MAX,
    PROGRESS_NOTE_MAX,
    REQUEST_CATEGORIES,
)

from .authentication import AgentRateThrottle, BugAgentKeyAuthentication
from .serialize import bug_detail, bug_summary

URGENCY_ORDER = {"urgent": 0, "high": 1, "medium": 2, "low": 3, "noise": 4}
TERMINAL = (BugReport.Status.RESOLVED, BugReport.Status.DISMISSED, BugReport.Status.ARCHIVED)


class ProgressSerializer(serializers.Serializer):
    phase = serializers.ChoiceField(choices=BUG_PROGRESS_PHASES)
    note = serializers.CharField(required=False, allow_blank=True, max_length=PROGRESS_NOTE_MAX)


class CardSerializer(serializers.Serializer):
    resolved_message = serializers.CharField(required=False, allow_blank=True, max_length=5000)
    display_title = serializers.CharField(required=False, allow_blank=True, max_length=DISPLAY_TITLE_MAX)
    category = serializers.ChoiceField(required=False, choices=REQUEST_CATEGORIES)
    plain_summary = serializers.CharField(required=False, allow_blank=True, max_length=PLAIN_SUMMARY_MAX)


class CommitSerializer(serializers.Serializer):
    commit_hash = serializers.CharField(required=False, allow_blank=True, max_length=64)
    admin_notes = serializers.CharField(required=False, allow_blank=True, max_length=2000)


class BlockedSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=900)
    run_url = serializers.URLField(required=False, allow_blank=True)


class MessageSerializer(serializers.Serializer):
    message = serializers.CharField(max_length=5000)


class ToFeatureSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200)
    problem = serializers.CharField(max_length=10000)
    desired_outcome = serializers.CharField(required=False, allow_blank=True, max_length=10000)
    message = serializers.CharField(max_length=5000)


class BulkSerializer(serializers.Serializer):
    ids = serializers.ListField(child=serializers.UUIDField(), min_length=1, max_length=200)
    admin_notes = serializers.CharField(required=False, allow_blank=True, max_length=2000)


class IncidentSerializer(serializers.Serializer):
    kind = serializers.RegexField(r"^[a-z0-9-]{1,40}$")
    branch = serializers.CharField(required=False, allow_blank=True, max_length=255)
    run_url = serializers.URLField(required=False, allow_blank=True)
    detail = serializers.CharField(required=False, allow_blank=True, max_length=2000)


def _valid(serializer_class, request):
    serializer = serializer_class(data=request.data)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


def _conflict(message):
    return Response({"error": message}, status=status.HTTP_409_CONFLICT)


def _drain_queue():
    from plane.bgtasks.agent_pipeline_task import fire_bug_routine_task

    if bug_ops.agent_queue().exists():
        fire_bug_routine_task.delay("se liberó la cola: quedan bugs abiertos")


def resolve_bug(bug, user, commit_hash="", admin_notes=""):
    """Idempotent: resolving twice neither changes the record nor emails twice."""
    if bug.status == BugReport.Status.RESOLVED:
        return False
    bug.status = BugReport.Status.RESOLVED
    bug.resolved_at = timezone.now()
    bug.resolved_by = user
    bug.claimed_at = None
    if commit_hash:
        bug.commit_hash = commit_hash
    notes = [n for n in (bug.admin_notes, admin_notes, "[Resuelto automáticamente por el agente]") if n]
    bug.admin_notes = "\n".join(notes)
    bug.save()
    notify.bug_resolved(bug)
    return True


class AgentBugBaseView(APIView):
    authentication_classes = [BugAgentKeyAuthentication]
    permission_classes = [IsAuthenticated]
    throttle_classes = [AgentRateThrottle]


class AgentBugListEndpoint(AgentBugBaseView):
    def get(self, request):
        wanted = request.query_params.get("status", "open")
        queryset = BugReport.objects.select_related("reported_by", "workspace")
        if wanted == "open":
            queryset = bug_ops.agent_queue().select_related("reported_by", "workspace")
        elif wanted != "all":
            queryset = queryset.filter(status=wanted)
        if request.query_params.get("reported_by"):
            queryset = queryset.filter(reported_by__email__iexact=request.query_params["reported_by"])
        if request.query_params.get("source"):
            queryset = queryset.filter(source=request.query_params["source"])
        items = [bug_summary(bug) for bug in queryset[:200]]
        items.sort(key=lambda b: (URGENCY_ORDER.get(b["urgency"], 9), b["created_at"] or ""))
        return Response(items)


class AgentBugDetailEndpoint(AgentBugBaseView):
    def get(self, request, pk):
        bug = get_object_or_404(BugReport.objects.select_related("reported_by", "workspace"), id=pk)
        return Response(bug_detail(bug, request))


class AgentBugActionEndpoint(AgentBugBaseView):
    def put(self, request, pk, action):
        handler = getattr(self, f"do_{action.replace('-', '_')}", None)
        if handler is None:
            return Response({"error": "Unknown action."}, status=status.HTTP_404_NOT_FOUND)
        with transaction.atomic():
            # of=("self",): Postgres refuses FOR UPDATE on the nullable side of the joined FKs.
            locked = BugReport.objects.select_for_update(of=("self",)).select_related("reported_by", "workspace")
            bug = get_object_or_404(locked, id=pk)
            return handler(request, bug)

    def do_claim(self, request, bug):
        if bug.status not in (BugReport.Status.OPEN, BugReport.Status.IN_PROGRESS):
            return _conflict(f"Bug is {bug.status}; only open bugs can be claimed.")
        if bug.blocked_at:
            return _conflict("Bug is blocked and waits for a person.")
        bug.status = BugReport.Status.IN_PROGRESS
        bug.claimed_at = timezone.now()
        bug.save(update_fields=["status", "claimed_at", "updated_at"])
        return Response(bug_summary(bug))

    def do_progress(self, request, bug):
        data = _valid(ProgressSerializer, request)
        if bug.status != BugReport.Status.IN_PROGRESS:
            return _conflict("Progress is only accepted while the bug is in_progress.")
        bug.progress = bug_ops.append_entry(bug.progress, bug_ops.progress_entry(data["phase"], data.get("note")))
        # A session that keeps reporting is alive: keep its claim from expiring.
        bug.claimed_at = timezone.now()
        bug.save(update_fields=["progress", "claimed_at", "updated_at"])
        return Response({"ok": True})

    def do_set_message(self, request, bug):
        data = _valid(CardSerializer, request)
        for field, value in data.items():
            setattr(bug, field, value)
        bug.save()
        return Response(bug_summary(bug))

    def do_mark_fixed(self, request, bug):
        data = _valid(CommitSerializer, request)
        if bug.status in (BugReport.Status.FIXED, BugReport.Status.RESOLVED):
            return Response(bug_summary(bug))
        if bug.status in TERMINAL:
            return _conflict(f"Bug is {bug.status}.")
        bug.status = BugReport.Status.FIXED
        bug.fixed_at = timezone.now()
        bug.claimed_at = None
        bug.commit_hash = data.get("commit_hash", "") or bug.commit_hash
        bug.save()
        transaction.on_commit(_drain_queue)
        return Response(bug_summary(bug))

    def do_resolve(self, request, bug):
        data = _valid(CommitSerializer, request)
        resolve_bug(bug, request.user, data.get("commit_hash", ""), data.get("admin_notes", ""))
        transaction.on_commit(_drain_queue)
        return Response(bug_summary(bug))

    def do_blocked(self, request, bug):
        data = _valid(BlockedSerializer, request)
        if bug.status in TERMINAL:
            return _conflict(f"Bug is {bug.status}.")
        bug.blocked_at = timezone.now()
        reason = data["reason"]
        if data.get("run_url"):
            reason = f"{reason}\n{data['run_url']}"
        bug.blocked_reason = reason
        bug.status = BugReport.Status.OPEN
        bug.claimed_at = None
        bug.save()
        notify.admins_bug_blocked(bug)
        return Response(bug_summary(bug))

    def do_dismiss_user_error(self, request, bug):
        data = _valid(MessageSerializer, request)
        if bug.status in TERMINAL:
            return _conflict(f"Bug is {bug.status}.")
        bug.status = BugReport.Status.DISMISSED
        bug.resolved_message = data["message"]
        bug.resolved_at = timezone.now()
        bug.claimed_at = None
        bug.admin_notes = "\n".join(n for n in (bug.admin_notes, "Error de uso: se envió guía a quien reportó.") if n)
        bug.save()
        notify.bug_user_guidance(bug)
        return Response(bug_summary(bug))

    def do_to_feature(self, request, bug):
        data = _valid(ToFeatureSerializer, request)
        if bug.status in TERMINAL:
            return _conflict(f"Bug is {bug.status}.")
        feature = bug_ops.derive_feature(
            bug,
            title=data["title"],
            problem=data["problem"],
            desired_outcome=data.get("desired_outcome", ""),
            message=data["message"],
            agent_user=request.user,
        )
        notify.bug_derived_to_feature(bug)
        transaction.on_commit(lambda: feature_ops.request_spec(feature, "derivada de un reporte de bug"))
        return Response({**bug_summary(bug), "feature_id": str(feature.id)})


class AgentBugBulkEndpoint(AgentBugBaseView):
    def put(self, request, action):
        if action not in ("resolve", "dismiss"):
            return Response({"error": "Unknown action."}, status=status.HTTP_404_NOT_FOUND)
        data = _valid(BulkSerializer, request)
        notes = data.get("admin_notes", "")
        changed = 0
        with transaction.atomic():
            for bug in BugReport.objects.select_for_update().filter(id__in=data["ids"]):
                if action == "resolve":
                    changed += resolve_bug(bug, request.user, admin_notes=notes)
                elif bug.status not in TERMINAL:
                    bug.status = BugReport.Status.DISMISSED
                    bug.claimed_at = None
                    bug.admin_notes = "\n".join(n for n in (bug.admin_notes, notes) if n)
                    bug.save()
                    changed += 1
        return Response({"changed": changed})


class AgentPipelineIncidentEndpoint(AgentBugBaseView):
    """CI reports a stuck pipeline (merge conflict, red preview): it becomes a blocking bug."""

    def post(self, request):
        data = _valid(IncidentSerializer, request)
        description = "\n".join(
            line
            for line in (
                f"Incidente de pipeline: {data['kind']}",
                data.get("detail", ""),
                f"Rama: {data['branch']}" if data.get("branch") else "",
                f"Corrida: {data['run_url']}" if data.get("run_url") else "",
            )
            if line
        )
        bug, _ = bug_ops.file_auto_bug_report(
            key=f"pipeline:{data['kind']}",
            description=description,
            error_type="pipeline-incident",
            url=data.get("run_url", ""),
            origin="ci",
        )
        if bug.severity != BugReport.Severity.BLOQUEANTE:
            bug.severity = BugReport.Severity.BLOQUEANTE
            bug.save(update_fields=["severity", "updated_at"])

        from plane.bgtasks.agent_pipeline_task import fire_bug_routine_task

        fire_bug_routine_task.delay(f"incidente de pipeline: {data['kind']}", str(bug.id), "urgent")
        return Response(bug_summary(bug), status=status.HTTP_201_CREATED)
