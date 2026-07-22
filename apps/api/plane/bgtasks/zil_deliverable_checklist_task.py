# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
Celery task that auto-spawns a deliverable's standard sub-issue checklist.

Dispatched from ``IssueViewSet.create``/``partial_update`` (see
``plane/app/views/issue/base.py``) whenever a deliverable-type label
(Branding, Web, Landing, Redes Sociales, Email, Merchandising — see
``plane.utils.zil_deliverable_checklists``) is present on the issue.

Idempotent: re-running for the same issue only creates the titles that are
still missing among its direct children (matched case-insensitively via
``titles_for_labels``), and every sub-issue this task creates is tagged
``external_source="zil_checklist"`` so they stay identifiable later.
"""

from celery import shared_task

from plane.db.models import Issue
from plane.utils.exception_logger import log_exception
from plane.utils.zil_deliverable_checklists import titles_for_labels

ZIL_CHECKLIST_EXTERNAL_SOURCE = "zil_checklist"


@shared_task
def zil_deliverable_checklist_task(issue_id, label_names):
    try:
        parent_issue = Issue.objects.filter(pk=issue_id).select_related("project").first()
        if parent_issue is None:
            return

        existing_titles = Issue.objects.filter(parent_id=issue_id, deleted_at__isnull=True).values_list(
            "name", flat=True
        )

        titles_to_create = titles_for_labels(label_names, existing_titles)
        if not titles_to_create:
            return

        for title in titles_to_create:
            sub_issue = Issue(
                project=parent_issue.project,
                parent=parent_issue,
                name=title[:255],
                description_html="<p></p>",
                external_source=ZIL_CHECKLIST_EXTERNAL_SOURCE,
                external_id=f"{issue_id}:{title.strip().lower()}"[:255],
            )
            sub_issue.save(created_by_id=parent_issue.created_by_id)
    except Exception as e:
        log_exception(e)
