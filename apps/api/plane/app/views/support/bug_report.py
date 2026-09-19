# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Django imports
from django.db import transaction
from django.utils import timezone

# Third party imports
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

# Module imports
from plane.agent_api.bugs import resolve_bug
from plane.agent_api.serialize import bug_detail, bug_summary
from plane.app.views.base import BaseAPIView
from plane.db.models import BugReport, FileAsset, Workspace
from plane.utils.agent_pipeline import bugs as bug_ops
from plane.utils.agent_pipeline import notify, routines
from plane.utils.agent_pipeline.constants import REOPEN_MIN_GAP
from plane.utils.agent_pipeline.permissions import IsInstanceAdmin, is_instance_admin

MAX_ATTACHMENTS = 5
MAX_CONSOLE_ENTRIES = 200


class AutoReportThrottle(UserRateThrottle):
    rate = "5/minute"
    scope = "bug_report_auto"


class ConsoleEntrySerializer(serializers.Serializer):
    level = serializers.CharField(max_length=20)
    args = serializers.ListField(child=serializers.CharField(max_length=2000, allow_blank=True), max_length=20)
    timestamp = serializers.CharField(max_length=40, required=False, allow_blank=True)


class BugReportCreateSerializer(serializers.Serializer):
    description = serializers.CharField(max_length=10000)
    urgent = serializers.BooleanField(required=False, default=False)
    url = serializers.CharField(required=False, allow_blank=True, max_length=2000, default="")
    user_agent = serializers.CharField(required=False, allow_blank=True, max_length=1000, default="")
    viewport = serializers.DictField(required=False, default=dict)
    system_info = serializers.DictField(required=False, default=dict)
    console_logs = ConsoleEntrySerializer(many=True, required=False, default=list)
    attachment_ids = serializers.ListField(
        child=serializers.UUIDField(), required=False, max_length=MAX_ATTACHMENTS, default=list
    )
    workspace_slug = serializers.CharField(required=False, allow_blank=True, max_length=48, default="")


class AutoReportSerializer(serializers.Serializer):
    fingerprint = serializers.RegexField(r"^[A-Za-z0-9_-]{4,64}$")
    error_type = serializers.CharField(max_length=255, allow_blank=True, required=False, default="Error")
    message = serializers.CharField(max_length=2000, allow_blank=True)
    stack = serializers.CharField(max_length=20000, allow_blank=True, required=False, default="")
    component_stack = serializers.CharField(max_length=20000, allow_blank=True, required=False, default="")
    url = serializers.CharField(required=False, allow_blank=True, max_length=2000, default="")
    system_info = serializers.DictField(required=False, default=dict)
    console_logs = ConsoleEntrySerializer(many=True, required=False, default=list)
    workspace_slug = serializers.CharField(required=False, allow_blank=True, max_length=48, default="")


class ReopenSerializer(serializers.Serializer):
    comment = serializers.CharField(max_length=5000)


class BulkActionSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=("resolve", "dismiss", "archive", "unblock"))
    ids = serializers.ListField(child=serializers.UUIDField(), min_length=1, max_length=200)
    admin_notes = serializers.CharField(required=False, allow_blank=True, max_length=2000, default="")


def _valid(serializer_class, request):
    serializer = serializer_class(data=request.data)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


def _workspace(slug, user):
    if not slug:
        return None
    return Workspace.objects.filter(slug=slug, workspace_member__member=user, workspace_member__is_active=True).first()


def _own_attachments(ids, user, entity_type):
    """Only assets this user uploaded for this purpose can be attached."""
    if not ids:
        return []
    return list(
        FileAsset.objects.filter(id__in=ids, created_by=user, entity_type=entity_type).values_list("id", flat=True)
    )


def _fire(reason, bug=None, urgency=None):
    from plane.bgtasks.agent_pipeline_task import fire_bug_routine_task

    bug_id = str(bug.id) if bug else None
    transaction.on_commit(lambda: fire_bug_routine_task.delay(reason, bug_id, urgency))


class BugReportEndpoint(BaseAPIView):
    def get_permissions(self):
        if self.request.method == "GET":
            return [IsInstanceAdmin()]
        return super().get_permissions()

    def get(self, request):
        queryset = BugReport.objects.select_related("reported_by", "workspace")
        if request.query_params.get("status"):
            queryset = queryset.filter(status=request.query_params["status"])
        if request.query_params.get("source"):
            queryset = queryset.filter(source=request.query_params["source"])
        if request.query_params.get("blocked") == "true":
            queryset = queryset.filter(blocked_at__isnull=False)
        return Response([bug_summary(bug) for bug in queryset[:300]])

    def post(self, request):
        data = _valid(BugReportCreateSerializer, request)
        attachment_ids = _own_attachments(
            data["attachment_ids"], request.user, FileAsset.EntityTypeContext.BUG_REPORT_ATTACHMENT
        )
        with transaction.atomic():
            bug = BugReport.objects.create(
                reported_by=request.user,
                workspace=_workspace(data["workspace_slug"], request.user),
                description=data["description"],
                severity=BugReport.Severity.BLOQUEANTE if data["urgent"] else BugReport.Severity.MOLESTO,
                source=BugReport.Source.MANUAL,
                origin="widget",
                url=data["url"],
                user_agent=data["user_agent"],
                viewport=data["viewport"],
                system_info=data["system_info"],
                console_logs=data["console_logs"][-MAX_CONSOLE_ENTRIES:],
                attachment_ids=[str(i) for i in attachment_ids],
                affected_user_ids=[str(request.user.id)],
                last_seen_at=timezone.now(),
            )
            FileAsset.objects.filter(id__in=attachment_ids).update(entity_identifier=str(bug.id))
            notify.admins_new_bug(bug)
            _fire("nuevo reporte de un usuario", bug, bug_ops.trigger_urgency_for_new(bug))
        return Response(bug_summary(bug), status=status.HTTP_201_CREATED)


class BugReportAutoEndpoint(BaseAPIView):
    """Browser crashes (ErrorBoundary, window.onerror, unhandled rejections), grouped by fingerprint."""

    throttle_classes = [AutoReportThrottle]

    def post(self, request):
        data = _valid(AutoReportSerializer, request)
        stack = "\n\n".join(s for s in (data["stack"], data["component_stack"]) if s)
        with transaction.atomic():
            bug, escalate = bug_ops.file_auto_bug_report(
                key=f"client:{data['fingerprint']}",
                description=f"{data['error_type']}: {data['message']}",
                error_type=data["error_type"],
                url=data["url"],
                origin="client",
                stack_trace=stack,
                system_info=data["system_info"],
                console_logs=data["console_logs"],
                user=request.user,
                workspace=_workspace(data["workspace_slug"], request.user),
            )
            if escalate:
                _fire(f"error en el navegador ({bug.occurrences} ocurrencias)", bug, bug_ops.classify_urgency(bug))
        return Response({"id": str(bug.id), "occurrences": bug.occurrences}, status=status.HTTP_202_ACCEPTED)


class MyBugReportsEndpoint(BaseAPIView):
    def get(self, request):
        queryset = BugReport.objects.filter(reported_by=request.user, source=BugReport.Source.MANUAL).select_related(
            "reported_by", "workspace"
        )
        return Response(
            [
                {**bug_summary(bug), "progress": bug.progress, "comments": bug.comments}
                for bug in queryset.exclude(status=BugReport.Status.ARCHIVED)[:100]
            ]
        )


class BugReportDetailEndpoint(BaseAPIView):
    def get(self, request, pk):
        bug = BugReport.objects.select_related("reported_by", "workspace").get(id=pk)
        if bug.reported_by_id != request.user.id and not is_instance_admin(request.user):
            return Response({"error": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(bug_detail(bug, request))


class BugReportReopenEndpoint(BaseAPIView):
    """Reenviar a soporte: the reporter says it is not fixed, or adds something."""

    def post(self, request, pk):
        data = _valid(ReopenSerializer, request)
        with transaction.atomic():
            bug = BugReport.objects.select_for_update().get(id=pk, reported_by=request.user)
            now = timezone.now()
            if bug.last_reopened_at and now - bug.last_reopened_at < REOPEN_MIN_GAP:
                return Response({"error": "Esperá unos minutos antes de volver a enviarlo."}, status=429)
            if bug.derived_feature_id:
                return Response(
                    {"error": "Este pedido ya pasó a Sugerencias; seguilo desde ahí."}, status=status.HTTP_409_CONFLICT
                )
            bug.comments = bug_ops.append_entry(
                bug.comments, bug_ops.comment_entry(request.user, "user", data["comment"])
            )
            bug.last_reopened_at = now
            if bug.status != BugReport.Status.IN_PROGRESS:
                bug.status = BugReport.Status.OPEN
                bug.resolved_at = None
                bug.fixed_at = None
            bug.save()
            _fire("quien reportó lo reenvió a soporte", bug, bug_ops.trigger_urgency_for_new(bug))
        return Response(bug_summary(bug))


class BugReportBulkEndpoint(BaseAPIView):
    permission_classes = [IsInstanceAdmin]

    def post(self, request):
        data = _valid(BulkActionSerializer, request)
        action, notes = data["action"], data["admin_notes"]
        changed = 0
        with transaction.atomic():
            for bug in BugReport.objects.select_for_update().filter(id__in=data["ids"]):
                if action == "resolve":
                    changed += resolve_bug(bug, request.user, admin_notes=notes)
                    continue
                if action == "unblock":
                    bug.blocked_at = None
                    bug.blocked_reason = ""
                else:
                    bug.status = BugReport.Status.DISMISSED if action == "dismiss" else BugReport.Status.ARCHIVED
                    bug.claimed_at = None
                bug.admin_notes = "\n".join(n for n in (bug.admin_notes, notes) if n)
                bug.save()
                changed += 1
            if action == "unblock":
                _fire("una persona destrabó reportes")
        return Response({"changed": changed})


class BugReportSendToFixerEndpoint(BaseAPIView):
    permission_classes = [IsInstanceAdmin]

    def post(self, request, pk):
        bug = BugReport.objects.get(id=pk)
        if bug.status in (BugReport.Status.RESOLVED, BugReport.Status.DISMISSED, BugReport.Status.ARCHIVED):
            bug.status = BugReport.Status.OPEN
        bug.blocked_at = None
        bug.blocked_reason = ""
        bug.save()
        # Synchronous on purpose: whoever pressed the button needs to know whether it went out.
        result = routines.fire_bug_routine("enviado al fixer por una persona", bug_id=str(bug.id), urgency="high")
        return Response(result)
