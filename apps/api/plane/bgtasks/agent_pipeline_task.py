# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
import logging

# Django imports
from django.core.mail import EmailMultiAlternatives, get_connection
from django.template.loader import render_to_string
from django.utils import timezone

# Third party imports
from celery import shared_task

# Module imports
from plane.db.models import FeatureRequest, User, Workspace
from plane.license.utils.instance_value import get_email_configuration
from plane.utils.agent_pipeline import bugs, features, routines
from plane.utils.agent_pipeline.constants import FEATURE_RUN_EXPIRY
from plane.utils.email import generate_plain_text_from_html
from plane.utils.exception_logger import log_exception

logger = logging.getLogger("plane.worker")


@shared_task
def fire_bug_routine_task(reason, bug_id=None, urgency=None):
    result = routines.fire_bug_routine(reason, bug_id=bug_id, urgency=urgency)
    logger.info("bug routine: %s (%s)", result, reason)
    return result


@shared_task
def fire_feature_routine_task(feature_id, mode, reason=""):
    feature = FeatureRequest.objects.filter(id=feature_id).first()
    if feature is None:
        return {"fired": False, "reason": "missing feature"}
    result = routines.fire_feature_routine(feature_id, mode, title=feature.title, reason=reason)
    if result.get("fired"):
        return result

    # The session never started: put the request back where a later fire can pick it up.
    note = f"No se pudo iniciar el análisis automático ({result.get('reason')})."
    if mode == "SPEC" and feature.status == FeatureRequest.Status.SPEC_RUNNING:
        feature.status = FeatureRequest.Status.SUBMITTED
        feature.spec_runs = max(0, feature.spec_runs - 1)
        feature.comments = bugs.append_entry(feature.comments, bugs.comment_entry(None, "agent", note))
        feature.save(update_fields=["status", "spec_runs", "comments", "updated_at"])
    elif mode == "BUILD" and feature.status == FeatureRequest.Status.BUILDING:
        build = dict(feature.build or {})
        build["claimed_at"] = None
        build["runs"] = max(0, int(build.get("runs", 1)) - 1)
        build["last_note"] = note
        feature.build = build
        feature.status = FeatureRequest.Status.APPROVED
        feature.save(update_fields=["build", "status", "updated_at"])
    return result


@shared_task
def agent_claim_sweep():
    """Every 10 minutes: free silent claims and re-fire while bugs sit open with no session.

    Every other caller of the bug routine is event-driven, so without this a queue with open
    bugs and no new traffic would never move.
    """
    freed = routines.expire_stale_bug_claims()
    pending = bugs.agent_queue().count()
    if not pending:
        return {"freed": freed, "pending": 0, "fired": False}
    result = routines.fire_bug_routine(f"barrido periódico: {pending} bug(s) abiertos sin sesión en curso")
    return {"freed": freed, "pending": pending, **result}


def _last_activity(feature, started_at):
    stamps = [started_at] + [p.get("at") for p in (feature.build or {}).get("progress", []) if p.get("at")]
    return max(s for s in stamps if s)


@shared_task
def feature_run_sweep():
    """Every 15 minutes: specs and builds with no sign of life go back to their queue."""
    cutoff = (timezone.now() - FEATURE_RUN_EXPIRY).isoformat()
    released = 0

    for feature in FeatureRequest.objects.filter(status=FeatureRequest.Status.SPEC_RUNNING):
        started = feature.spec_requested_at.isoformat() if feature.spec_requested_at else ""
        if started and started < cutoff:
            feature.status = FeatureRequest.Status.SUBMITTED
            feature.save(update_fields=["status", "updated_at"])
            released += 1

    for feature in FeatureRequest.objects.filter(status=FeatureRequest.Status.BUILDING):
        build = feature.build or {}
        started = build.get("claimed_at") or ""
        # A blocked build waits for a person; re-dispatching it would hit the same wall.
        if started and not build.get("blocked_at") and _last_activity(feature, started) < cutoff:
            build = dict(feature.build or {})
            build["claimed_at"] = None
            build["last_note"] = "La construcción se quedó sin señales de vida y volvió a la cola."
            feature.build = build
            feature.status = FeatureRequest.Status.APPROVED
            feature.save(update_fields=["build", "status", "updated_at"])
            released += 1

    drained = features.drain_feature_queue("barrido periódico")
    return {"released": released, "drained": drained}


@shared_task
def file_server_error_task(payload):
    try:
        user = User.objects.filter(id=payload.get("user_id")).first() if payload.get("user_id") else None
        slug = payload.get("workspace_slug")
        workspace = Workspace.objects.filter(slug=slug).first() if slug else None
        bug, escalate = bugs.file_auto_bug_report(
            key=payload["key"],
            description=payload.get("description", ""),
            error_type=payload.get("error_type", ""),
            url=payload.get("url", ""),
            origin="server",
            stack_trace=payload.get("stack_trace", ""),
            user=user,
            workspace=workspace,
        )
        if escalate:
            routines.fire_bug_routine(
                f"error del servidor ({bug.occurrences} ocurrencias)",
                bug_id=str(bug.id),
                urgency=bugs.classify_urgency(bug),
            )
    except Exception as e:
        log_exception(e)


@shared_task
def send_support_email_task(to, subject, heading, paragraphs, cta_label=None, cta_url=None):
    try:
        html_content = render_to_string(
            "emails/support/notice.html",
            {
                "heading": heading,
                "paragraphs": [p for p in paragraphs if p],
                "cta_label": cta_label,
                "cta_url": cta_url,
            },
        )
        text_content = generate_plain_text_from_html(html_content)
        (
            EMAIL_HOST,
            EMAIL_HOST_USER,
            EMAIL_HOST_PASSWORD,
            EMAIL_PORT,
            EMAIL_USE_TLS,
            EMAIL_USE_SSL,
            EMAIL_FROM,
        ) = get_email_configuration()
        connection = get_connection(
            host=EMAIL_HOST,
            port=int(EMAIL_PORT),
            username=EMAIL_HOST_USER,
            password=EMAIL_HOST_PASSWORD,
            use_tls=EMAIL_USE_TLS == "1",
            use_ssl=EMAIL_USE_SSL == "1",
        )
        for recipient in to:
            msg = EmailMultiAlternatives(
                subject=subject, body=text_content, from_email=EMAIL_FROM, to=[recipient], connection=connection
            )
            msg.attach_alternative(html_content, "text/html")
            msg.send()
    except Exception as e:
        log_exception(e)
