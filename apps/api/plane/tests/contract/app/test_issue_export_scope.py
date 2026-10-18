# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""An export holds exactly the work items its requester can read.

The endpoint passes the requested project ids through unchecked: the export task is what
scopes the rows. These tests drive the real endpoint and the real task, so they hold whichever
of the two does the scoping.
"""

import json
import zipfile
from unittest import mock

import pytest
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from plane.bgtasks.export_task import issue_export_task
from plane.db.models import ExporterHistory, Issue, Project, ProjectMember, User, WorkspaceMember


def _project(session_client, workspace, name, identifier, network):
    response = session_client.post(
        f"/api/workspaces/{workspace.slug}/projects/",
        {"name": name, "identifier": identifier, "network": network},
        format="json",
    )
    assert response.status_code == status.HTTP_201_CREATED
    project = Project.objects.get(pk=response.data["id"])
    assert project.network == network
    return project


def _issue(workspace, project, name, author):
    # BaseModel.save() would overwrite a plain created_by with the (absent) request user.
    issue = Issue(workspace=workspace, project=project, name=name)
    issue.save(created_by_id=author.id)
    return issue


@pytest.fixture
def secret_project(session_client, workspace, create_user):
    """A brand the requester is not on: created (and joined) by the workspace owner only."""
    project = _project(session_client, workspace, "KFC", "KFC", network=0)
    _issue(workspace, project, "KFC secret campaign", create_user)
    return project


@pytest.fixture
def member(workspace):
    user = User.objects.create(email="wendys@zil.test", username="wendys")
    WorkspaceMember.objects.create(workspace=workspace, member=user, role=15)
    return user


@pytest.fixture
def own_project(session_client, workspace, create_user, member):
    project = _project(session_client, workspace, "Wendys", "WEN", network=0)
    ProjectMember.objects.create(workspace=workspace, project=project, member=member, role=15)
    _issue(workspace, project, "Wendys campaign", create_user)
    return project


def _client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _export(client, workspace, **payload):
    """POST the export, run the task it queued, and return the exported work item names."""
    with mock.patch("plane.app.views.exporter.base.issue_export_task") as queued:
        response = client.post(
            f"/api/workspaces/{workspace.slug}/export-issues/", {"provider": "json", **payload}, format="json"
        )
    assert response.status_code == status.HTTP_200_OK
    kwargs = queued.delay.call_args.kwargs

    uploads = []
    with mock.patch(
        "plane.bgtasks.export_task.upload_to_s3", side_effect=lambda zip_file, *args: uploads.append(zip_file)
    ):
        issue_export_task(**kwargs)
    assert uploads, ExporterHistory.objects.get(token=kwargs["token_id"]).reason

    with zipfile.ZipFile(uploads[0]) as archive:
        return {row["name"] for name in archive.namelist() for row in json.loads(archive.read(name))}


@pytest.mark.contract
class TestIssueExportProjectScope:
    @pytest.mark.django_db
    def test_member_gets_nothing_from_a_secret_project_they_are_not_on(self, workspace, secret_project, member):
        client = _client(member)
        assert _export(client, workspace, project=[str(secret_project.id)]) == set()
        assert _export(client, workspace, project=[str(secret_project.id)], multiple=True) == set()

    @pytest.mark.django_db
    def test_mixed_request_exports_only_the_requesters_projects(self, workspace, secret_project, own_project, member):
        requested = [str(own_project.id), str(secret_project.id)]
        assert _export(_client(member), workspace, project=requested) == {"Wendys campaign"}
        assert _export(_client(member), workspace, project=requested, multiple=True) == {"Wendys campaign"}

    @pytest.mark.django_db
    def test_default_request_exports_only_the_requesters_projects(self, workspace, secret_project, own_project, member):
        assert _export(_client(member), workspace) == {"Wendys campaign"}

    @pytest.mark.django_db
    def test_left_project_is_not_exported(self, workspace, secret_project, member):
        ProjectMember.objects.create(
            workspace=workspace, project=secret_project, member=member, role=15, is_active=False
        )
        assert _export(_client(member), workspace, project=[str(secret_project.id)]) == set()

    @pytest.mark.django_db
    def test_soft_deleted_membership_is_not_exported(self, workspace, secret_project, member):
        # allow_permission never sees a soft-deleted row (default manager), even one left is_active.
        ProjectMember.objects.create(
            workspace=workspace, project=secret_project, member=member, role=20, deleted_at=timezone.now()
        )
        assert _export(_client(member), workspace, project=[str(secret_project.id)]) == set()

    @pytest.mark.django_db
    def test_workspace_admin_needs_to_be_on_the_project_like_everywhere_else(self, workspace, secret_project):
        # Workspace admins see secret projects in the project list, but reading their work items
        # takes a project membership (allow_permission at PROJECT level); exports follow suit.
        admin = User.objects.create(email="admin@zil.test", username="zil-admin")
        WorkspaceMember.objects.create(workspace=workspace, member=admin, role=20)
        assert _export(_client(admin), workspace, project=[str(secret_project.id)]) == set()

        ProjectMember.objects.create(workspace=workspace, project=secret_project, member=admin, role=20)
        assert _export(_client(admin), workspace, project=[str(secret_project.id)]) == {"KFC secret campaign"}

    @pytest.mark.django_db
    def test_project_guest_exports_only_what_they_can_read(self, workspace, secret_project, member):
        ProjectMember.objects.create(workspace=workspace, project=secret_project, member=member, role=5)
        _issue(workspace, secret_project, "Guest request", member)
        requested = [str(secret_project.id)]

        assert _export(_client(member), workspace, project=requested) == {"Guest request"}

        Project.objects.filter(pk=secret_project.pk).update(guest_view_all_features=True)
        assert _export(_client(member), workspace, project=requested) == {"Guest request", "KFC secret campaign"}
