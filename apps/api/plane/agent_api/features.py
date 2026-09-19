# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""/api/agent/features/* — the feature agent's API.

There is deliberately no approve, reject or flag route: with this key the agent cannot
authorize its own build or turn its own work on.
"""

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
from plane.db.models import AgentFeatureFlag, FeatureRequest
from plane.utils.agent_pipeline import bugs as bug_ops
from plane.utils.agent_pipeline import features as feature_ops
from plane.utils.agent_pipeline import notify
from plane.utils.agent_pipeline.constants import (
    DISPLAY_TITLE_MAX,
    FEATURE_PROGRESS_PHASES,
    PLAIN_SUMMARY_MAX,
    PROGRESS_NOTE_MAX,
    REQUEST_CATEGORIES,
)
from plane.utils.agent_pipeline.permissions import is_instance_admin

from .authentication import AgentRateThrottle, FeatureAgentKeyAuthentication
from .serialize import feature_detail, feature_summary

S = FeatureRequest.Status
SPEC_PHASE = (S.SUBMITTED, S.SPEC_RUNNING, S.NEEDS_INFO)


def _strings(max_length=500):
    return serializers.ListField(
        child=serializers.CharField(max_length=max_length), required=False, max_length=100, default=list
    )


class SpecSerializer(serializers.Serializer):
    summary = serializers.CharField(max_length=5000)
    approach = serializers.CharField(max_length=10000)
    affected_areas = _strings()
    files_touched = _strings()
    db_changes = serializers.CharField(required=False, allow_blank=True, max_length=5000, default="")
    new_endpoints = _strings()
    new_env_vars = _strings()
    risks = _strings(2000)
    rollback = serializers.CharField(required=False, allow_blank=True, max_length=5000, default="")
    effort = serializers.ChoiceField(choices=("S", "M", "L", "XL"))
    open_questions = _strings(1000)
    blast_radius = serializers.ChoiceField(choices=("low", "medium", "high"))
    flag_key = serializers.RegexField(r"^[a-z][a-zA-Z0-9]{2,59}$")
    display_title = serializers.CharField(required=False, allow_blank=True, max_length=DISPLAY_TITLE_MAX)
    category = serializers.ChoiceField(required=False, choices=REQUEST_CATEGORIES)
    plain_summary = serializers.CharField(required=False, allow_blank=True, max_length=PLAIN_SUMMARY_MAX)


class QuestionsSerializer(serializers.Serializer):
    questions = serializers.ListField(child=serializers.CharField(max_length=1000), min_length=1, max_length=10)


class BuildStatusSerializer(serializers.Serializer):
    state = serializers.ChoiceField(choices=("in_review", "queued", "blocked"))
    note = serializers.CharField(required=False, allow_blank=True, max_length=2000, default="")
    pr_url = serializers.URLField(required=False, allow_blank=True, default="")
    pr_number = serializers.IntegerField(required=False, allow_null=True, default=None)
    guard_report = serializers.CharField(required=False, allow_blank=True, max_length=20000, default="")


class ProgressSerializer(serializers.Serializer):
    phase = serializers.ChoiceField(choices=FEATURE_PROGRESS_PHASES)
    note = serializers.CharField(required=False, allow_blank=True, max_length=PROGRESS_NOTE_MAX, default="")


class MergedSerializer(serializers.Serializer):
    commit_hash = serializers.CharField(required=False, allow_blank=True, max_length=64, default="")


class CommentSerializer(serializers.Serializer):
    text = serializers.CharField(max_length=5000)


def _valid(serializer_class, request):
    serializer = serializer_class(data=request.data)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


def _conflict(message):
    return Response({"error": message}, status=status.HTTP_409_CONFLICT)


def should_auto_approve(feature):
    """A clean first spec approves itself when an admin asked for it, or when its impact is low.

    A re-spec means someone already intervened, so that decision goes back to a person.
    """
    spec = feature.spec or {}
    if spec.get("open_questions"):
        return False
    if feature.spec_runs > 1:
        return False
    return is_instance_admin(feature.requested_by) or spec.get("blast_radius") == "low"


class AgentFeatureBaseView(APIView):
    authentication_classes = [FeatureAgentKeyAuthentication]
    permission_classes = [IsAuthenticated]
    throttle_classes = [AgentRateThrottle]


class AgentFeatureListEndpoint(AgentFeatureBaseView):
    def get(self, request):
        queryset = FeatureRequest.objects.select_related("requested_by", "workspace")
        wanted = request.query_params.get("status")
        if wanted:
            queryset = queryset.filter(status=wanted)
        else:
            queryset = queryset.filter(status__in=(S.SPEC_RUNNING, S.BUILDING))
        return Response([feature_summary(f) for f in queryset[:200]])


class AgentFeatureDetailEndpoint(AgentFeatureBaseView):
    def get(self, request, pk):
        feature = get_object_or_404(FeatureRequest.objects.select_related("requested_by", "workspace"), id=pk)
        return Response(feature_detail(feature, request))


class AgentFeatureActionEndpoint(AgentFeatureBaseView):
    def put(self, request, pk, action):
        return self._dispatch(request, pk, action)

    def post(self, request, pk, action):
        return self._dispatch(request, pk, action)

    def _dispatch(self, request, pk, action):
        handler = getattr(self, f"do_{action.replace('-', '_')}", None)
        if handler is None:
            return Response({"error": "Unknown action."}, status=status.HTTP_404_NOT_FOUND)
        with transaction.atomic():
            locked = FeatureRequest.objects.select_for_update(of=("self",)).select_related("requested_by", "workspace")
            feature = get_object_or_404(locked, id=pk)
            return handler(request, feature)

    def do_spec(self, request, feature):
        data = _valid(SpecSerializer, request)
        if feature.status not in SPEC_PHASE:
            return _conflict(f"Feature is {feature.status}; specs are only accepted before approval.")
        card = {k: data.pop(k) for k in ("display_title", "category", "plain_summary") if k in data}
        for field, value in card.items():
            setattr(feature, field, value)
        feature.spec = {**data, "generated_at": timezone.now().isoformat()}
        feature.flag_key = data["flag_key"]
        feature.status = S.SPEC_READY

        if should_auto_approve(feature):
            feature.status = S.APPROVED
            feature.approval = {
                "by": "auto",
                "at": timezone.now().isoformat(),
                "notes": "Aprobada automáticamente (primer análisis, sin preguntas abiertas).",
            }
            feature.save()
            notify.requester_feature_update(
                feature,
                "Tu sugerencia se empieza a construir",
                "Analizamos tu sugerencia y quedó aprobada. Ya empezamos a construirla; podés seguir el avance.",
            )
            transaction.on_commit(lambda: feature_ops.request_build(feature, "aprobada automáticamente"))
        else:
            feature.save()
            notify.admins_feature_needs_decision(feature)
            notify.requester_feature_update(
                feature,
                "Analizamos tu sugerencia",
                "Ya tenemos el análisis de lo que pediste. Ahora lo revisa el equipo para decidir si se construye.",
            )
        return Response(feature_summary(feature))

    def do_needs_info(self, request, feature):
        data = _valid(QuestionsSerializer, request)
        if feature.status not in SPEC_PHASE:
            # In BUILD, asking would drop the build claim while the session is still alive.
            return _conflict("Questions are only accepted while specing. In BUILD, report build-status blocked.")
        feature.status = S.NEEDS_INFO
        feature.spec = {**(feature.spec or {}), "open_questions": data["questions"]}
        text = "\n".join(f"- {q}" for q in data["questions"])
        feature.comments = bug_ops.append_entry(feature.comments, bug_ops.comment_entry(None, "agent", text))
        feature.save()
        notify.requester_feature_update(
            feature, "Necesitamos un dato sobre tu sugerencia", f"Para avanzar necesitamos que nos cuentes:\n{text}"
        )
        return Response(feature_summary(feature))

    def do_build_status(self, request, feature):
        data = _valid(BuildStatusSerializer, request)
        build = dict(feature.build or {})
        if data["state"] == "blocked":
            if feature.status != S.BUILDING:
                return _conflict("Only a running build can be blocked; merged code has nothing left to block.")
            build.update({"blocked_at": timezone.now().isoformat(), "last_note": data["note"]})
            feature.build = build
            feature.save()
            notify.requester_feature_update(feature, "Tu sugerencia necesita una revisión", data["note"])
            return Response(feature_summary(feature))

        if feature.status not in (S.BUILDING, S.IN_REVIEW, S.QUEUED):
            return _conflict(f"Feature is {feature.status}.")
        now = timezone.now().isoformat()
        build.update({k: data[k] for k in ("pr_url", "pr_number", "guard_report") if data.get(k)})
        build["in_review_at" if data["state"] == "in_review" else "queued_at"] = now
        feature.build = build
        feature.status = S.IN_REVIEW if data["state"] == "in_review" else S.QUEUED
        feature.save()
        transaction.on_commit(feature_ops.drain_feature_queue)
        return Response(feature_summary(feature))

    def do_progress(self, request, feature):
        data = _valid(ProgressSerializer, request)
        build = dict(feature.build or {})
        if feature.status != S.BUILDING or build.get("blocked_at"):
            return _conflict("Progress is only accepted while the build is running.")
        build["progress"] = bug_ops.append_entry(
            build.get("progress"), bug_ops.progress_entry(data["phase"], data["note"])
        )
        feature.build = build
        feature.save(update_fields=["build", "updated_at"])
        return Response({"ok": True})

    def do_merged(self, request, feature):
        data = _valid(MergedSerializer, request)
        if feature.status == S.MERGED:
            return Response(feature_summary(feature))
        if feature.status not in (S.BUILDING, S.IN_REVIEW, S.QUEUED):
            return _conflict(f"Feature is {feature.status}.")
        build = dict(feature.build or {})
        build["merged_at"] = timezone.now().isoformat()
        if data["commit_hash"]:
            build["commit_hash"] = data["commit_hash"]
        feature.build = build
        feature.status = S.MERGED
        feature.save()
        if feature.flag_key:
            AgentFeatureFlag.objects.get_or_create(key=feature.flag_key, defaults={"feature": feature})
        notify.requester_feature_update(
            feature,
            "Tu sugerencia ya está construida",
            "Lo que pediste ya está en Zil Ops. Va a aparecer apenas el equipo lo active.",
        )
        transaction.on_commit(feature_ops.drain_feature_queue)
        return Response(feature_summary(feature))

    def do_comment(self, request, feature):
        data = _valid(CommentSerializer, request)
        feature.comments = bug_ops.append_entry(feature.comments, bug_ops.comment_entry(None, "agent", data["text"]))
        feature.save(update_fields=["comments", "updated_at"])
        return Response({"ok": True})
