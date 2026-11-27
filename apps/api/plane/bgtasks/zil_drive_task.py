# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Whether the Drive videos of the brands' client portals still open, so Ops warns the team.

A link is checked as the person who pasted it (plane/utils/zil_drive.py) when it is added or
changed, whenever a client opens the post, and every two hours for the posts clients see that are
not long past. The result stays on the link (metadata.zil_drive), which Ops' calendar reads.
"""

from datetime import timedelta

from celery import shared_task
from django.db.models import Q
from django.utils import timezone

from plane.db.models import IssueLink, ZilClientPortal
from plane.utils.zil_client_portal import visible_issues
from plane.utils.zil_drive import check_link

MAX_LINKS = 1000
PAST_DAYS = 7


@shared_task
def check_drive_link(link_id):
    """Check one link right away (just added or changed), without what was cached about it."""
    link = IssueLink.objects.filter(pk=link_id).select_related("created_by").first()
    if link is not None:
        check_link(link, fresh=True)


@shared_task
def check_portal_drive_links():
    """Check the Drive links of every post a client sees, from a week ago on."""
    since = timezone.now().date() - timedelta(days=PAST_DAYS)
    checked = 0
    for portal in ZilClientPortal.objects.filter(enabled=True).select_related("project"):
        issues = visible_issues(portal.project).filter(Q(target_date__isnull=True) | Q(target_date__gte=since))
        links = IssueLink.objects.filter(issue__in=issues, url__contains="drive.google.com").select_related(
            "created_by"
        )
        for link in links[: MAX_LINKS - checked]:
            check_link(link)
            checked += 1
        if checked >= MAX_LINKS:
            break
    return checked
