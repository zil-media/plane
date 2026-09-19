# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Fires the Claude Code Routines (cloud agent sessions) that work the bug and feature queues.

A routine is a saved cloud session bound to this repo. Firing it is one POST with a text
payload; the payload carries the Ops API URL and the lane's own agent key, which the session
uses to read and update the queue. The detailed instructions live in the routine itself
(docs/agents/*_INSTRUCTIONS.md is the repo mirror).
"""

# Python imports
import logging
import os

# Django imports
from django.conf import settings
from django.utils import timezone

# Third party imports
import requests

# Module imports
from plane.db.models import AgentPipelineConfig, BugReport
from plane.settings.redis import redis_instance

from .constants import BUG_ROUTINE_COOLDOWN, CLAIM_EXPIRY

logger = logging.getLogger("plane.worker")

BUG_COOLDOWN_KEY = "agent_pipeline:bug_routine:cooldown"
BYPASS_URGENCIES = ("urgent", "high")


def api_base_url():
    return (os.environ.get("AGENT_API_BASE_URL") or settings.WEB_URL or "").rstrip("/")


def resolve_agent_key(env_var):
    """The lane's self-minted key, or None when it is missing or looks like an Anthropic secret."""
    key = os.environ.get(env_var, "").strip()
    if not key:
        logger.warning("agent routine skipped: %s not configured", env_var)
        return None
    # The key travels inside the routine transcript. An Anthropic token pasted here by
    # mistake (they sit next to each other in the env) would leak into it.
    if key.startswith("sk-ant-"):
        logger.error("agent routine aborted: %s looks like an Anthropic secret", env_var)
        return None
    return key


def post_routine(url, token, text, label):
    """POSTs the trigger text to a routine endpoint. Never raises."""
    try:
        response = requests.post(
            url,
            json={"text": text},
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "anthropic-version": "2023-06-01",
            },
            timeout=20,
        )
    except requests.RequestException as e:
        logger.warning("%s routine fire error: %s", label, e)
        return False
    if not response.ok:
        logger.warning("%s routine fire failed: %s %s", label, response.status_code, response.text[:200])
        return False
    logger.info("%s routine fired", label)
    return True


def _take_cooldown():
    """Atomically takes the shared cooldown window. True if this caller won it."""
    ttl = int(BUG_ROUTINE_COOLDOWN.total_seconds())
    return bool(redis_instance().set(BUG_COOLDOWN_KEY, timezone.now().isoformat(), nx=True, ex=ttl))


def _release_cooldown():
    redis_instance().delete(BUG_COOLDOWN_KEY)


def fire_bug_routine(reason, bug_id=None, urgency=None):
    """Starts a bug-fix session unless one is already working the queue.

    One session drains the whole queue, so new bugs normally just wait for it. `urgent` and
    `high` skip both the active-session gate and the cooldown.
    """
    url = os.environ.get("ANTHROPIC_OPS_BUG_ROUTINE_URL")
    token = os.environ.get("ANTHROPIC_OPS_BUG_ROUTINE_TOKEN")
    if not url or not token:
        return {"fired": False, "reason": "not configured"}
    if not AgentPipelineConfig.get().bug_agent_enabled:
        return {"fired": False, "reason": "disabled"}
    # Resolved before the cooldown: a bad key must not burn the window.
    api_key = resolve_agent_key("OPS_BUG_AGENT_API_KEY")
    if not api_key:
        return {"fired": False, "reason": "bad agent key"}

    expire_stale_bug_claims()

    bypass = urgency in BYPASS_URGENCIES
    took_cooldown = False
    if not bypass:
        active = BugReport.objects.filter(
            status=BugReport.Status.IN_PROGRESS, claimed_at__gte=timezone.now() - CLAIM_EXPIRY
        ).exists()
        if active:
            return {"fired": False, "reason": "session in flight"}
        if not _take_cooldown():
            return {"fired": False, "reason": "cooldown"}
        took_cooldown = True

    text = "\n".join(
        [
            "AUTOMATED BUG-FIX TRIGGER (from Zil Ops production)",
            "",
            "Connection details for the bug API (sourced from this deployment's config):",
            f"API_URL: {api_base_url()}",
            f"AGENT_API_KEY: {api_key}",
            "",
            "Context for this run:",
            f"- Reason: {reason or 'N/A'}",
            f"- Bug ID: {bug_id or 'N/A'}",
            f"- Urgency: {urgency or 'unknown'}",
            f"- Triggered at: {timezone.now().isoformat()}",
            "",
            "Follow your saved instructions: fetch the bug(s) via",
            "GET ${API_URL}/api/agent/bugs/?status=open with Authorization: Bearer ${AGENT_API_KEY},",
            "fix, commit with Bug-Id trailers, push to your claude/** branch, then confirm via the API.",
        ]
    )
    ok = post_routine(url, token, text, "Bug")
    if not ok:
        # A fire that never happened must not hold the window for the next caller.
        if took_cooldown:
            _release_cooldown()
        return {"fired": False, "reason": "post failed"}
    if bypass:
        # Starts the window for normal fires, but only once the POST went out.
        redis_instance().set(BUG_COOLDOWN_KEY, timezone.now().isoformat(), ex=int(BUG_ROUTINE_COOLDOWN.total_seconds()))
    return {"fired": True}


def fire_feature_routine(feature_id, mode, title="", reason=""):
    """SPEC writes an impact assessment and no code; BUILD implements an approved spec.

    No cooldown here: the gate is the feature's own state, checked by the caller.
    """
    url = os.environ.get("ANTHROPIC_OPS_FEATURE_ROUTINE_URL")
    token = os.environ.get("ANTHROPIC_OPS_FEATURE_ROUTINE_TOKEN")
    if not url or not token:
        return {"fired": False, "reason": "not configured"}
    if mode not in ("SPEC", "BUILD"):
        return {"fired": False, "reason": "invalid mode"}
    api_key = resolve_agent_key("OPS_FEATURE_AGENT_API_KEY")
    if not api_key:
        return {"fired": False, "reason": "bad agent key"}

    base = api_base_url()
    text = "\n".join(
        [
            "AUTOMATED FEATURE TRIGGER (from Zil Ops production)",
            "",
            "Connection details for the feature API (sourced from this deployment's config):",
            f"API_URL: {base}",
            f"AGENT_API_KEY: {api_key}",
            "",
            "Context for this run:",
            f"MODE: {mode}",
            f"- Feature ID: {feature_id}",
            f"- Title: {title or 'N/A'}",
            f"- Reason: {reason or 'N/A'}",
            f"- Triggered at: {timezone.now().isoformat()}",
            "",
            "This trigger carries CONTEXT ONLY — the detailed instructions live in this routine.",
            "Read MODE above and follow the matching section of your saved instructions:",
            "SPEC writes an Impact Spec and NO code. BUILD implements on feat/agent/<Feature ID>",
            "and pushes there — never to preview, never to a claude/** branch. You never approve,",
            "reject, or merge anything: those are human-only actions and the API will not let you.",
            f"Fetch the request via GET {base}/api/agent/features/{feature_id}/",
            "with Authorization: Bearer <AGENT_API_KEY>.",
        ]
    )
    if not post_routine(url, token, text, "Feature"):
        return {"fired": False, "reason": "post failed"}
    return {"fired": True}


def expire_stale_bug_claims():
    """Returns bugs whose session went silent to the queue. Returns how many were freed."""
    cutoff = timezone.now() - CLAIM_EXPIRY
    return BugReport.objects.filter(status=BugReport.Status.IN_PROGRESS, claimed_at__lt=cutoff).update(
        status=BugReport.Status.OPEN, claimed_at=None
    )
