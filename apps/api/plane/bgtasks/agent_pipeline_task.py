# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
import logging

# Django imports
from django.core.mail import EmailMultiAlternatives, get_connection
from django.template.loader import render_to_string
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

# Third party imports
from celery import shared_task
import requests

# Module imports
from plane.db.models import FeatureRequest, User, Workspace
from plane.license.utils.instance_value import get_email_configuration
from plane.utils.agent_pipeline import bugs, features, routines
from plane.utils.agent_pipeline.constants import FEATURE_RUN_EXPIRY, MAX_SPEC_RUNS
from plane.utils.exception_logger import log_exception

logger = logging.getLogger("plane.worker")


@shared_task
def fire_bug_routine_task(reason, bug_id=None, urgency=None):
    result = routines.fire_bug_routine(reason, bug_id=bug_id, urgency=urgency)
    logger.info("bug routine: %s (%s)", result, reason)
    return result


def _released_spec_status(feature):
    """Where an analysis that never finished leaves the request: a spec it already had stays ready to
    decide (dropping it to "received" hid it from the admins and, past the run cap, from the sweep)."""
    has_spec = bool((feature.spec or {}).get("generated_at"))
    return FeatureRequest.Status.SPEC_READY if has_spec else FeatureRequest.Status.SUBMITTED


@shared_task
def fire_feature_routine_task(feature_id, mode, reason="", previous=None):
    feature = FeatureRequest.objects.filter(id=feature_id).first()
    if feature is None:
        return {"fired": False, "reason": "missing feature"}
    previous_failure = (feature.build or {}).get("for_agent", "") if mode == "BUILD" else ""
    result = routines.fire_feature_routine(
        feature_id, mode, title=feature.title, reason=reason, previous_failure=previous_failure
    )
    if result.get("fired"):
        return result

    # The session never started: put the request back where a later fire can pick it up. Re-read under
    # a lock: the POST above can take a while, and a hold, a rejection or a comment made meanwhile
    # must not be overwritten by the copy read before it.
    what = "el análisis" if mode == "SPEC" else "el desarrollo"
    note = f"No se pudo iniciar {what} automático ({result.get('reason')})."
    with transaction.atomic():
        feature = FeatureRequest.objects.select_for_update().filter(id=feature_id).first()
        if feature is None:
            return result
        if mode == "SPEC" and feature.status == FeatureRequest.Status.SPEC_RUNNING:
            # Back where it was asked from: a ready spec stays ready to decide, a hold stays held, and an
            # answered question stays answered (waiting for someone to relaunch it), not "ready" with the
            # answer never analysed. The sweep retries submitted ones.
            feature.status = previous if previous in features.SPEC_STARTABLE else _released_spec_status(feature)
            # The failed attempt counts toward the run cap: the sweep retries submitted ones, and with a
            # persistent failure (bad key, outage) uncounted attempts retried forever, one comment each.
            # Not on an answered question: an agent comment after the answer reads as a new question, so
            # it went back to the requester instead of to the admin who relaunches it.
            if feature.status != FeatureRequest.Status.NEEDS_INFO:
                feature.comments = bugs.append_entry(feature.comments, bugs.comment_entry(None, "agent", note))
            feature.save(update_fields=["status", "comments", "updated_at"])
        elif mode == "BUILD" and feature.status == FeatureRequest.Status.BUILDING:
            build = dict(feature.build or {})
            build["claimed_at"] = None
            # Counted too (see above): the drain re-fires approved builds, so an uncounted failure looped.
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


SPEC_RETRIES_PER_SWEEP = 3


@shared_task
def feature_run_sweep():
    """Every 15 minutes: specs and builds with no sign of life go back to their queue."""
    cutoff = (timezone.now() - FEATURE_RUN_EXPIRY).isoformat()
    released = 0

    for feature in FeatureRequest.objects.filter(status=FeatureRequest.Status.SPEC_RUNNING):
        started = feature.spec_requested_at.isoformat() if feature.spec_requested_at else ""
        if started and started < cutoff:
            feature.status = _released_spec_status(feature)
            feature.save(update_fields=["status", "updated_at"])
            released += 1

    for feature in FeatureRequest.objects.filter(status=FeatureRequest.Status.BUILDING):
        build = feature.build or {}
        started = build.get("claimed_at") or ""
        # blocked_at only on rows from before builds retried themselves: those waited for a person.
        if started and not build.get("blocked_at") and _last_activity(feature, started) < cutoff:
            build = dict(feature.build or {})
            build["claimed_at"] = None
            build["last_note"] = "La construcción se quedó sin señales de vida y volvió a la cola."
            feature.build = build
            feature.status = FeatureRequest.Status.APPROVED
            feature.save(update_fields=["build", "status", "updated_at"])
            released += 1

    # A ready spec has nobody to decide it (a re-spec that died leaves one): decide it here.
    from plane.agent_api.features import decide_spec

    for feature_id in FeatureRequest.objects.filter(status=FeatureRequest.Status.SPEC_READY).values_list(
        "id", flat=True
    ):
        with transaction.atomic():
            feature = (
                FeatureRequest.objects.select_for_update()
                .filter(id=feature_id, status=FeatureRequest.Status.SPEC_READY)
                .first()
            )
            if feature is not None:
                decide_spec(feature)

    # Specs released above, or that never started (agent off at the time, or the fire failed), go back
    # on their own: nothing else re-requests a submitted feature. A few per tick, oldest first, within
    # the automatic-run cap (request_spec checks it and the agent switch).
    pending_since = timezone.now() - FEATURE_RUN_EXPIRY
    retried = 0
    for feature in FeatureRequest.objects.filter(
        Q(spec_requested_at__isnull=True) | Q(spec_requested_at__lt=pending_since),
        status=FeatureRequest.Status.SUBMITTED,
        spec_runs__lt=MAX_SPEC_RUNS,
    ).order_by("created_at")[:SPEC_RETRIES_PER_SWEEP]:
        queued, _ = features.request_spec(feature, "barrido periódico: análisis pendiente")
        retried += int(queued)

    drained = features.drain_feature_queue("barrido periódico")
    return {"released": released, "retried": retried, "drained": drained}


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


# A support email that couldn't reach the relay (Workspace restarting, a deploy, Gmail failing) is
# tried again a few times, a minute apart, instead of being lost with only a log line.
SUPPORT_MAIL_RETRIES = 3


def _nothing_was_sent(error):
    """A failure that guarantees the email didn't go out: the connection never happened, or the relay
    answered 5xx (it answers 502 only when it delivered to nobody). A read timeout is NOT one: the
    relay may have sent it, and a second try would send it twice."""
    if isinstance(error, requests.ReadTimeout):
        return False
    if isinstance(error, requests.ConnectionError):
        return True
    return isinstance(error, RuntimeError) and str(error).startswith("relay HTTP 5")


@shared_task(bind=True, max_retries=SUPPORT_MAIL_RETRIES)
def send_support_email_task(self, to, subject, heading, paragraphs, cta_label=None, cta_url=None):
    failed = []
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
        # Production relays through Zil (ZilEmailBackend → /api/sso/mail), which re-renders the email
        # from this text: its title is the subject and its button the html's CTA, one line per
        # paragraph. Derived from the html, a <br> left no separator (the agent's questions ran into
        # one line) and the heading, the CTA label and the signature came out as extra lines.
        lines = [heading] if heading and heading != subject else []
        lines += [line.strip() for p in paragraphs if p for line in str(p).split("\n") if line.strip()]
        text_content = "\n".join(lines)
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
            try:
                msg.send()
            except Exception as e:
                if not _nothing_was_sent(e):
                    raise
                # Only who didn't get it goes again: the rest already has it.
                failed.append(recipient)
                logger.warning("support mail to %s not sent (%s), will retry", recipient, e)
    except Exception as e:
        log_exception(e)
        return
    if failed:
        if self.request.retries >= SUPPORT_MAIL_RETRIES:
            log_exception(RuntimeError(f"support mail '{subject}' not delivered to {len(failed)} after retries"))
            return
        raise self.retry(
            args=(failed, subject, heading, paragraphs, cta_label, cta_url), countdown=60 * (self.request.retries + 1)
        )
