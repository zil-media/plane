# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Wake Zil AI agents (ZIL_AGENT bots) when a person mentions or assigns them.

`dispatch_zil_agent_events` runs inside the `issue_activity` Celery task, after
the activity rows are saved. It detects *new* agent mentions (issue description
or comment) and *newly added* agent assignees, and queues one
`deliver_zil_agent_event` per (event, agent), which POSTs to the Zil Workspace
at {ZIL_BASE_URL}/api/agent/ai-agents/ops-events with X-Zil-Service-Key.
Actions performed by an agent bot are ignored so agents never wake each other.
"""

# Python imports
import logging
import os

# Third party imports
import requests
from bs4 import BeautifulSoup
from celery import shared_task

# Django imports
from django.conf import settings

# Module imports
from plane.bgtasks.notification_task import extract_comment_mentions, extract_mentions
from plane.db.models import BotTypeEnum, Issue, User
from plane.utils.exception_logger import log_exception
from plane.utils.uuid import is_valid_uuid

logger = logging.getLogger("plane.worker")

OPS_EVENTS_PATH = "/api/agent/ai-agents/ops-events"
MAX_TEXT_CHARS = 8000
DELIVERY_TIMEOUT_SECONDS = 10

_ISSUE_TYPES = ("issue.activity.created", "issue.activity.updated")
_COMMENT_TYPES = ("comment.activity.created", "comment.activity.updated")


def _zil_config():
    base = os.environ.get("ZIL_BASE_URL", "").rstrip("/")
    secret = os.environ.get("ZIL_SERVICE_SECRET", "")
    return (base, secret) if base and secret else (None, None)


def _is_agent(user):
    return bool(user and user.is_bot and user.bot_type == BotTypeEnum.ZIL_AGENT)


def _html_to_text(html, names):
    """Plain text of an editor HTML value; user mentions become `@Name`."""
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all("mention-component"):
        if tag.get("entity_name") == "user_mention":
            name = names.get(str(tag.get("entity_identifier")), "")
            tag.replace_with(f"@{name}" if name else "")
    return soup.get_text(" ", strip=True)[:MAX_TEXT_CHARS]


def _new_comment_mentions(new_html, old_html):
    old = set(extract_comment_mentions(old_html)) if old_html else set()
    return [m for m in extract_comment_mentions(new_html) if m not in old]


def dispatch_zil_agent_events(
    type, requested_data, current_instance, issue_id, project_id, actor_id, epoch, issue_activities, origin=None
):
    """Queue an ops-event for each agent newly mentioned/assigned by a non-agent actor."""
    if type not in _ISSUE_TYPES + _COMMENT_TYPES or not issue_id:
        return
    if not all(_zil_config()):
        return
    actor = User.objects.filter(pk=actor_id).first()
    if actor is None or _is_agent(actor):
        return

    # (kind, agent_id, source_id, comment_id, html) — source_id makes eventId unique per change.
    candidates = []
    if type in _ISSUE_TYPES:
        previous = set(extract_mentions(current_instance))
        for agent_id in extract_mentions(requested_data):
            if agent_id not in previous:
                candidates.append(("mention", agent_id, f"issue:{issue_id}:{epoch}", None, None))
        for activity in issue_activities:
            if activity.field == "assignees" and activity.verb == "updated" and activity.new_identifier:
                candidates.append(("assigned", str(activity.new_identifier), f"activity:{activity.id}", None, None))
    else:
        for activity in issue_activities:
            if activity.field != "comment" or activity.verb not in ("created", "updated"):
                continue
            for agent_id in _new_comment_mentions(activity.new_value, activity.old_value):
                candidates.append(
                    (
                        "mention",
                        agent_id,
                        f"comment:{activity.issue_comment_id}:{activity.id}",
                        activity.issue_comment_id,
                        activity.new_value,
                    )
                )

    agent_ids = {c[1] for c in candidates if is_valid_uuid(c[1])}
    if not agent_ids:
        return
    agents = {
        str(u.id): u
        for u in User.objects.filter(
            pk__in=agent_ids,
            is_bot=True,
            bot_type=BotTypeEnum.ZIL_AGENT,
            is_active=True,
            member_project__project_id=project_id,
            member_project__is_active=True,
        ).distinct()
    }
    if not agents:
        return

    issue = Issue.objects.select_related("project", "workspace").filter(pk=issue_id).first()
    if issue is None:
        return

    def mention_names(html):
        ids = [i for i in extract_comment_mentions(html) if is_valid_uuid(i)] if html else []
        return {str(u.id): u.display_name for u in User.objects.filter(pk__in=ids)}

    description_html = issue.description_html or ""
    description_text = _html_to_text(description_html, mention_names(description_html))
    web_base = (settings.WEB_URL or settings.APP_BASE_URL or origin or "").rstrip("/")
    issue_url = f"{web_base}/{issue.workspace.slug}/projects/{issue.project_id}/issues/{issue.id}"

    for kind, agent_id, source_id, comment_id, html in candidates:
        agent = agents.get(agent_id)
        if agent is None:
            continue
        text = _html_to_text(html, mention_names(html)) if html is not None else description_text
        payload = {
            "eventId": f"ops:{kind}:{source_id}:{agent_id}",
            "kind": kind,
            "agentEmail": agent.email,
            "actor": {"name": actor.display_name or actor.first_name or actor.email, "email": actor.email},
            "workspaceSlug": issue.workspace.slug,
            "projectId": str(issue.project_id),
            "projectIdentifier": issue.project.identifier,
            "issueId": str(issue.id),
            "issueSequence": issue.sequence_id,
            "issueName": issue.name,
            "commentId": str(comment_id) if comment_id else None,
            "text": text,
            "url": issue_url,
        }
        deliver_zil_agent_event.delay(payload)


@shared_task(bind=True, max_retries=4)
def deliver_zil_agent_event(self, payload):
    """POST one ops-event to the Zil Workspace; 5xx/429/network errors are retried, then logged."""
    base, secret = _zil_config()
    if not base:
        return
    try:
        resp = requests.post(
            f"{base}{OPS_EVENTS_PATH}",
            json=payload,
            headers={"X-Zil-Service-Key": secret},
            timeout=DELIVERY_TIMEOUT_SECONDS,
        )
        if resp.status_code >= 500 or resp.status_code == 429:
            raise requests.HTTPError(f"ops-event {payload.get('eventId')} got HTTP {resp.status_code}")
        if resp.status_code >= 400:
            logger.warning("Zil ops-event %s rejected: HTTP %s", payload.get("eventId"), resp.status_code)
    except requests.RequestException as e:
        if self.request.retries >= self.max_retries:
            logger.error("Zil ops-event %s dropped after %s retries: %s", payload.get("eventId"), self.max_retries, e)
            log_exception(e, warning=True)
            return
        raise self.retry(exc=e, countdown=30 * (2**self.request.retries))
