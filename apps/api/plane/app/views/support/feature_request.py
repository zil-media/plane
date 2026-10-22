# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Django imports
from django.db import transaction
from django.utils import timezone

# Third party imports
from rest_framework import exceptions, serializers, status
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

# Module imports
from plane.agent_api.serialize import feature_detail, feature_summary
from plane.app.views.base import BaseAPIView
from plane.db.models import AgentFeatureFlag, AgentPipelineConfig, FeatureRequest, FileAsset
from plane.utils.agent_pipeline import bugs as bug_ops
from plane.utils.agent_pipeline import features as feature_ops
from plane.utils.agent_pipeline import notify
from plane.utils.agent_pipeline.constants import REQUEST_CATEGORIES
from plane.utils.agent_pipeline.flags import enabled_flag_keys
from plane.utils.agent_pipeline.permissions import IsInstanceAdmin, is_instance_admin

from .bug_report import _own_attachments, _valid, _workspace

S = FeatureRequest.Status


class FeatureRequestCreateThrottle(UserRateThrottle):
    rate = "5/hour"
    scope = "feature_request_create"

    def allow_request(self, request, view):
        if request.method != "POST":
            return True
        return super().allow_request(request, view)


class SuggestionsThrottled(exceptions.APIException):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    default_detail = "Ya envió varias sugerencias en esta hora. Puede enviar otra dentro de un rato."


class FeatureRequestCreateSerializer(serializers.Serializer):
    title = serializers.CharField(min_length=6, max_length=200)
    problem = serializers.CharField(min_length=20, max_length=10000)
    desired_outcome = serializers.CharField(required=False, allow_blank=True, max_length=10000, default="")
    priority = serializers.ChoiceField(choices=FeatureRequest.Priority.values, required=False, default="media")
    source_url = serializers.CharField(required=False, allow_blank=True, max_length=2000, default="")
    attachment_ids = serializers.ListField(child=serializers.UUIDField(), required=False, max_length=5, default=list)
    workspace_slug = serializers.CharField(required=False, allow_blank=True, max_length=48, default="")


class CommentSerializer(serializers.Serializer):
    text = serializers.CharField(max_length=5000)


class DecisionSerializer(serializers.Serializer):
    notes = serializers.CharField(required=False, allow_blank=True, max_length=2000, default="")
    flag_key = serializers.RegexField(r"^[a-z][a-zA-Z0-9]{2,59}$", required=False)


class FlagSerializer(serializers.Serializer):
    enabled = serializers.BooleanField()


class ConfigSerializer(serializers.Serializer):
    bug_agent_enabled = serializers.BooleanField(required=False)
    feature_agent_enabled = serializers.BooleanField(required=False)
    max_builds_per_week = serializers.IntegerField(required=False, min_value=0, max_value=50)


def _config_dict(config):
    return {
        "bug_agent_enabled": config.bug_agent_enabled,
        "feature_agent_enabled": config.feature_agent_enabled,
        "max_builds_per_week": config.max_builds_per_week,
    }


class SupportMeEndpoint(BaseAPIView):
    def get(self, request):
        config = AgentPipelineConfig.get()
        return Response(
            {
                "is_admin": is_instance_admin(request.user),
                "categories": REQUEST_CATEGORIES,
                **_config_dict(config),
            }
        )


class AgentPipelineConfigEndpoint(BaseAPIView):
    permission_classes = [IsInstanceAdmin]

    def get(self, request):
        return Response(_config_dict(AgentPipelineConfig.get()))

    def patch(self, request):
        data = _valid(ConfigSerializer, request)
        config = AgentPipelineConfig.get()
        for field, value in data.items():
            setattr(config, field, value)
        config.save()
        return Response(_config_dict(config))


class FeatureFlagsEndpoint(BaseAPIView):
    def get(self, request):
        return Response({"enabled": enabled_flag_keys()})


class FeatureRequestEndpoint(BaseAPIView):
    throttle_classes = [FeatureRequestCreateThrottle]

    def throttled(self, request, wait):
        # The person sees this in the modal. Not DRF's Throttled: the instance exception handler turns
        # that into a bare RATE_LIMIT_EXCEEDED code, and the modal could only say "try again".
        raise SuggestionsThrottled()

    def get(self, request):
        queryset = FeatureRequest.objects.select_related("requested_by", "workspace")
        if request.query_params.get("scope") == "mine":
            queryset = queryset.filter(requested_by=request.user)
        if request.query_params.get("status"):
            queryset = queryset.filter(status__in=request.query_params["status"].split(","))
        return Response([feature_summary(f) for f in queryset[:300]])

    def post(self, request):
        data = _valid(FeatureRequestCreateSerializer, request)
        attachment_ids = _own_attachments(
            data["attachment_ids"], request.user, FileAsset.EntityTypeContext.FEATURE_REQUEST_ATTACHMENT
        )
        with transaction.atomic():
            feature = FeatureRequest.objects.create(
                requested_by=request.user,
                workspace=_workspace(data["workspace_slug"], request.user),
                title=data["title"],
                problem=data["problem"],
                desired_outcome=data["desired_outcome"],
                priority=data["priority"],
                source_url=data["source_url"],
                attachment_ids=[str(i) for i in attachment_ids],
            )
            FileAsset.objects.filter(id__in=attachment_ids).update(entity_identifier=str(feature.id))
            notify.admins_new_feature(feature)
            transaction.on_commit(lambda: feature_ops.request_spec(feature, "sugerencia nueva"))
        return Response(feature_summary(feature), status=status.HTTP_201_CREATED)


class FeatureRequestDetailEndpoint(BaseAPIView):
    def get(self, request, pk):
        feature = FeatureRequest.objects.select_related("requested_by", "workspace").get(id=pk)
        data = feature_detail(feature, request)
        if not is_instance_admin(request.user):
            # CI's note for the next session (run link, failing check) isn't the requester's.
            data["build"] = {k: v for k, v in (data.get("build") or {}).items() if k != "for_agent"}
        return Response(data)


class FeatureRequestCommentEndpoint(BaseAPIView):
    def post(self, request, pk):
        data = _valid(CommentSerializer, request)
        is_admin = is_instance_admin(request.user)
        with transaction.atomic():
            feature = FeatureRequest.objects.select_for_update().get(id=pk)
            is_requester = feature.requested_by_id == request.user.id
            if not (is_requester or is_admin):
                return Response({"error": "Not allowed."}, status=status.HTTP_403_FORBIDDEN)
            role = "admin" if is_admin and not is_requester else "user"
            feature.comments = bug_ops.append_entry(
                feature.comments, bug_ops.comment_entry(request.user, role, data["text"])
            )
            feature.save(update_fields=["comments", "updated_at"])
            answers_agent = feature.status == S.NEEDS_INFO and is_requester
        if not answers_agent:
            return Response(feature_summary(feature))
        # Answering the agent's questions sends the request back to analysis. After the commit, and
        # with the result in the answer: the comment always lands, but the analysis may not restart
        # (feature agent off), and the panel has to say which one happened.
        queued, reason = feature_ops.request_spec(feature, "quien pidió respondió las preguntas", force=True)
        return Response({**feature_summary(feature), "respec": {"queued": queued, "reason": reason}})


class FeatureRequestRespecEndpoint(BaseAPIView):
    # Redoing the analysis resumes a paused request, and pausing is an admin's call.
    BY_REQUESTER = (S.SUBMITTED, S.SPEC_READY, S.NEEDS_INFO)
    BY_ADMIN = (*BY_REQUESTER, S.ON_HOLD)

    def post(self, request, pk):
        feature = FeatureRequest.objects.get(id=pk)
        is_admin = is_instance_admin(request.user)
        if feature.requested_by_id != request.user.id and not is_admin:
            return Response({"error": "Not allowed."}, status=status.HTTP_403_FORBIDDEN)
        if feature.status not in (self.BY_ADMIN if is_admin else self.BY_REQUESTER):
            return Response({"error": f"La sugerencia está en {feature.status}."}, status=status.HTTP_409_CONFLICT)
        queued, reason = feature_ops.request_spec(feature, "se pidió un nuevo análisis", force=True)
        return Response({"queued": queued, "reason": reason, **feature_summary(feature)})


class FeatureRequestDecisionEndpoint(BaseAPIView):
    """approve | reject | hold | rebuild — human-only, there is no agent route for any of these."""

    permission_classes = [IsInstanceAdmin]

    ALLOWED_FROM = {
        "approve": (S.SPEC_READY, S.NEEDS_INFO, S.ON_HOLD, S.SUBMITTED),
        # in_review/queued need a human exit too: a PR closed without merging, or a batch that dropped it,
        # would otherwise leave the feature there forever. Rejected code that already merged stays dark.
        "reject": (
            S.SUBMITTED,
            S.SPEC_READY,
            S.NEEDS_INFO,
            S.ON_HOLD,
            S.APPROVED,
            S.BUILDING,
            S.IN_REVIEW,
            S.QUEUED,
        ),
        "hold": (S.SUBMITTED, S.SPEC_READY, S.NEEDS_INFO, S.APPROVED, S.BUILDING, S.IN_REVIEW),
        "rebuild": (S.BUILDING, S.APPROVED, S.IN_REVIEW, S.ON_HOLD),
    }

    def post(self, request, pk, decision):
        if decision not in self.ALLOWED_FROM:
            return Response({"error": "Unknown decision."}, status=status.HTTP_404_NOT_FOUND)
        data = _valid(DecisionSerializer, request)
        with transaction.atomic():
            feature = FeatureRequest.objects.select_for_update().get(id=pk)
            if feature.status not in self.ALLOWED_FROM[decision]:
                return Response({"error": f"La sugerencia está en {feature.status}."}, status=status.HTTP_409_CONFLICT)
            resumed = feature.status == S.ON_HOLD
            record = {
                "by": str(request.user.id),
                "by_name": request.user.display_name,
                "at": timezone.now().isoformat(),
                "notes": data["notes"],
            }
            if decision == "approve" and (feature.spec or {}).get("already_exists"):
                # Nothing to build: approving it is agreeing with the analysis, so it closes with the
                # how-to instead of sending a build session out to say the same thing and stop.
                feature.approval = record
                # The how-to is the analysis; the approver's note goes after it, it doesn't replace it.
                how_to = "\n\n".join(p for p in ((feature.spec or {}).get("summary", ""), data["notes"]) if p)
                feature_ops.close_already_existing(feature, how_to, by=request.user)
                return Response(feature_summary(feature))
            if decision in ("approve", "rebuild"):
                if data.get("flag_key"):
                    feature.flag_key = data["flag_key"]
                if not feature.flag_key:
                    return Response(
                        {"error": "Hace falta una clave de flag para construirla apagada."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                if decision == "approve":
                    feature.approval = record
                build = dict(feature.build or {})
                # A person decided: the previous stop's note no longer explains anything while it waits,
                # and the run cap of an earlier build doesn't apply (approving a redone spec after a
                # run-cap hold put it straight back on hold).
                build.update({"blocked_at": None, "claimed_at": None, "last_note": "", "manual_retry": True})
                feature.build = build
                feature.status = S.APPROVED
                feature.save()
            elif decision == "reject":
                feature.rejection = record
                feature.status = S.REJECTED
                feature.save()
                if feature.requested_by_id != request.user.id:
                    notify.requester_feature_update(
                        feature,
                        "Sobre tu sugerencia",
                        data["notes"] or "Revisamos tu sugerencia y por ahora no la vamos a construir.",
                    )
            else:
                feature.status = S.ON_HOLD
                feature.save()
                if feature.requested_by_id != request.user.id:
                    notify.requester_feature_update(
                        feature,
                        "Pausamos tu sugerencia",
                        data["notes"] or "Por ahora la pausamos. Te avisamos cuando se retome.",
                    )
        if decision not in ("approve", "rebuild"):
            return Response(feature_summary(feature))
        # After the commit, with the result in the answer: an approved feature only starts building
        # when the lane has room (agent on, no other build in flight, weekly cap), and whoever pressed
        # the button has to know whether it started or why not.
        fired, reason = feature_ops.request_build(feature, f"decisión: {decision}")
        # Like an automatic approval, the requester hears it, and a resumed one too (the hold email
        # promised it). A plain rebuild is a retry, not news to them.
        if (decision == "approve" or resumed) and feature.requested_by_id != request.user.id:
            notify.requester_feature_approved(feature, fired)
        return Response({**feature_summary(feature), "build": {"fired": fired, "reason": reason}})


class FeatureRequestFlagEndpoint(BaseAPIView):
    permission_classes = [IsInstanceAdmin]

    def post(self, request, pk):
        data = _valid(FlagSerializer, request)
        feature = FeatureRequest.objects.get(id=pk)
        if not feature.flag_key:
            return Response({"error": "La sugerencia no tiene flag."}, status=status.HTTP_400_BAD_REQUEST)
        flag, _ = AgentFeatureFlag.objects.get_or_create(key=feature.flag_key, defaults={"feature": feature})
        flag.enabled = data["enabled"]
        flag.enabled_by = request.user if data["enabled"] else None
        flag.enabled_at = timezone.now() if data["enabled"] else None
        flag.save()
        return Response({"key": flag.key, "enabled": flag.enabled})
