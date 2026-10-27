# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import pytest
from django.utils import timezone
from rest_framework import status

from plane.db.models import AgentFeatureFlag, Issue, IssueComment, Project, ProjectMember, State, User, WorkspaceMember


@pytest.fixture
def trash_flag(db):
    return AgentFeatureFlag.objects.create(key="trashRestore", enabled=True)


@pytest.fixture
def project(workspace, create_user):
    project = Project.objects.create(name="Trash", identifier="TRS", workspace=workspace)
    ProjectMember.objects.create(project=project, member=create_user, role=20, workspace=workspace)
    return project


@pytest.fixture
def state(project):
    return State.objects.create(name="Todo", project=project, workspace=project.workspace)


def _soft_delete_issue_with_comment(project, state):
    issue = Issue.objects.create(name="Lost", project=project, workspace=project.workspace, state=state)
    comment = IssueComment.objects.create(
        issue=issue, project=project, workspace=project.workspace, comment_html="<p>hi</p>"
    )
    now = timezone.now()
    Issue.all_objects.filter(pk=issue.pk).update(deleted_at=now)
    IssueComment.all_objects.filter(pk=comment.pk).update(deleted_at=now + timezone.timedelta(seconds=1))
    return issue, comment


def _list_url(workspace, project):
    return f"/api/workspaces/{workspace.slug}/projects/{project.id}/trash/"


@pytest.mark.contract
class TestProjectTrash:
    @pytest.mark.django_db
    def test_flag_off_returns_404(self, session_client, workspace, project):
        response = session_client.get(_list_url(workspace, project))
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.django_db
    def test_lists_only_deleted_issues_within_window(self, session_client, workspace, project, state, trash_flag):
        issue, _ = _soft_delete_issue_with_comment(project, state)
        old = Issue.objects.create(name="Expired", project=project, workspace=workspace, state=state)
        Issue.all_objects.filter(pk=old.pk).update(deleted_at=timezone.now() - timezone.timedelta(days=3650))
        Issue.objects.create(name="Alive", project=project, workspace=workspace, state=state)

        response = session_client.get(_list_url(workspace, project), {"type": "issue"})

        assert response.status_code == status.HTTP_200_OK
        assert [item["id"] for item in response.data] == [str(issue.id)]
        assert response.data[0]["days_remaining"] > 0

    @pytest.mark.django_db
    def test_member_cannot_list(self, session_client, workspace, project, trash_flag, create_user):
        ProjectMember.objects.filter(member=create_user, project=project).update(role=15)
        WorkspaceMember.objects.filter(member=create_user, workspace=workspace).update(role=15)

        response = session_client.get(_list_url(workspace, project))

        assert response.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.django_db
    def test_admin_of_other_project_cannot_list(self, session_client, workspace, project, trash_flag):
        other = Project.objects.create(name="Other", identifier="OTH", workspace=workspace)
        other_admin = User.objects.create(email="x@example.com", username="x")
        WorkspaceMember.objects.create(workspace=workspace, member=other_admin, role=15)
        ProjectMember.objects.create(project=other, member=other_admin, role=20, workspace=workspace)
        session_client.force_authenticate(user=other_admin)

        response = session_client.get(_list_url(workspace, project))

        assert response.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.django_db
    def test_restore_brings_back_issue_and_its_comment(self, session_client, workspace, project, state, trash_flag):
        issue, comment = _soft_delete_issue_with_comment(project, state)

        response = session_client.post(f"{_list_url(workspace, project)}issue/{issue.id}/restore/")

        assert response.status_code == status.HTTP_200_OK
        assert Issue.objects.filter(pk=issue.pk).exists()
        assert IssueComment.objects.filter(pk=comment.pk).exists()

    @pytest.mark.django_db
    def test_restore_leaves_independently_deleted_comment_hidden(
        self, session_client, workspace, project, state, trash_flag
    ):
        issue, _ = _soft_delete_issue_with_comment(project, state)
        earlier = IssueComment.objects.create(
            issue=issue, project=project, workspace=workspace, comment_html="<p>x</p>"
        )
        IssueComment.all_objects.filter(pk=earlier.pk).update(deleted_at=timezone.now() - timezone.timedelta(days=2))

        session_client.post(f"{_list_url(workspace, project)}issue/{issue.id}/restore/")

        assert not IssueComment.objects.filter(pk=earlier.pk).exists()

    @pytest.mark.django_db
    def test_restore_blocked_when_state_was_deleted(self, session_client, workspace, project, state, trash_flag):
        issue, _ = _soft_delete_issue_with_comment(project, state)
        State.all_objects.filter(pk=state.pk).update(deleted_at=timezone.now())

        response = session_client.post(f"{_list_url(workspace, project)}issue/{issue.id}/restore/")

        assert response.status_code == status.HTTP_409_CONFLICT
        assert not Issue.objects.filter(pk=issue.pk).exists()

    @pytest.mark.django_db
    def test_restore_unknown_item_is_404(self, session_client, workspace, project, state, trash_flag):
        alive = Issue.objects.create(name="Alive", project=project, workspace=workspace, state=state)

        response = session_client.post(f"{_list_url(workspace, project)}issue/{alive.id}/restore/")

        assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.contract
class TestWorkspaceProjectTrash:
    @pytest.mark.django_db
    def test_restore_deleted_project(self, session_client, workspace, project, trash_flag):
        Project.all_objects.filter(pk=project.pk).update(deleted_at=timezone.now())
        url = f"/api/workspaces/{workspace.slug}/trash/projects/"

        listing = session_client.get(url)
        restored = session_client.post(f"{url}{project.id}/restore/")

        assert [item["id"] for item in listing.data] == [str(project.id)]
        assert restored.status_code == status.HTTP_200_OK
        assert Project.objects.filter(pk=project.pk).exists()
