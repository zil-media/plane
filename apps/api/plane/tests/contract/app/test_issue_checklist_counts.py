# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Contract tests for the work item checklist counters (workItemChecklist).

Issue.save() recounts the to-do list items in description_html into checklist_total /
checklist_completed, and the work item list endpoints return both fields.
"""

from io import StringIO

import pytest
from django.core.management import call_command
from rest_framework import status

from plane.db.models import Issue, Project, ProjectMember

ISSUES_URL = "/api/workspaces/{slug}/projects/{project_id}/issues/"


def _task_list(*checked):
    items = "".join(
        f'<li data-type="taskItem" data-checked="{"true" if c else "false"}"><p>item {i}</p></li>'
        for i, c in enumerate(checked)
    )
    return f'<ul data-type="taskList">{items}</ul>'


@pytest.fixture
def project(db, workspace, create_user):
    project = Project.objects.create(name="Checklist Project", identifier="CHK", workspace=workspace)
    ProjectMember.objects.create(project=project, member=create_user, workspace=workspace, role=20)
    return project


def _find_issue(payload, issue_id):
    """Locate an issue dict anywhere in a (possibly grouped / paginated) list response."""
    if isinstance(payload, dict):
        if str(payload.get("id")) == issue_id and "name" in payload:
            return payload
        for value in payload.values():
            found = _find_issue(value, issue_id)
            if found:
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = _find_issue(value, issue_id)
            if found:
                return found
    return None


@pytest.mark.contract
class TestIssueChecklistCounts:
    @pytest.mark.django_db
    def test_create_patch_and_list_return_counts(self, session_client, workspace, project):
        url = ISSUES_URL.format(slug=workspace.slug, project_id=project.id)

        response = session_client.post(
            url,
            {"name": "Edit videos", "description_html": _task_list(True, False, False)},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.data
        issue_id = str(response.data["id"])
        assert response.data["checklist_total"] == 3
        assert response.data["checklist_completed"] == 1

        response = session_client.patch(
            f"{url}{issue_id}/",
            {"description_html": _task_list(True, True, False, True)},
            format="json",
        )
        assert response.status_code in (status.HTTP_200_OK, status.HTTP_204_NO_CONTENT), response.data
        issue = Issue.objects.get(id=issue_id)
        assert (issue.checklist_total, issue.checklist_completed) == (4, 3)

        response = session_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        listed = _find_issue(response.json(), issue_id)
        assert listed is not None
        assert listed["checklist_total"] == 4
        assert listed["checklist_completed"] == 3

    @pytest.mark.django_db
    def test_non_description_update_keeps_counts(self, project):
        issue = Issue.objects.create(name="A", project=project, description_html=_task_list(True, False))
        assert (issue.checklist_total, issue.checklist_completed) == (2, 1)

        issue.name = "B"
        issue.save(update_fields=["name"])
        issue.refresh_from_db()
        assert (issue.checklist_total, issue.checklist_completed) == (2, 1)

        issue.description_html = "<p>no list</p>"
        issue.save(update_fields=["description_html"])
        issue.refresh_from_db()
        assert (issue.checklist_total, issue.checklist_completed) == (0, 0)

    @pytest.mark.django_db
    def test_backfill_is_idempotent_and_keeps_updated_at(self, project):
        issue = Issue.objects.create(name="Old", project=project, description_html=_task_list(True, True, False))
        # Simulate a row written before the columns existed.
        Issue.all_objects.filter(id=issue.id).update(checklist_total=0, checklist_completed=0)
        stale = Issue.objects.create(name="Stale", project=project, description_html="<p></p>")
        Issue.all_objects.filter(id=stale.id).update(checklist_total=5, checklist_completed=2)
        before = Issue.objects.get(id=issue.id).updated_at

        out = StringIO()
        call_command("backfill_issue_checklist_counts", stdout=out)
        assert "2 work items" in out.getvalue()
        issue.refresh_from_db()
        stale.refresh_from_db()
        assert (issue.checklist_total, issue.checklist_completed) == (3, 2)
        assert (stale.checklist_total, stale.checklist_completed) == (0, 0)
        assert issue.updated_at == before

        out = StringIO()
        call_command("backfill_issue_checklist_counts", stdout=out)
        assert "0 work items" in out.getvalue()
