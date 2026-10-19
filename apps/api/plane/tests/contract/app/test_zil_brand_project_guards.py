# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from unittest import mock

import pytest
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from plane.db.models import BotTypeEnum, Project, ProjectMember, User, WorkspaceMember, ZilBrandProject
from plane.utils.zil_agents import sync_zil_agent_project_memberships
from plane.utils.zil_brand_projects import apply_brand_roster, ensure_migration_project

KFC = "0123456789abcdef0123c001"


@pytest.fixture(autouse=True)
def quiet_tasks():
    with (
        mock.patch("plane.app.views.project.base.model_activity.delay"),
        mock.patch("plane.app.views.project.base.webhook_activity.delay"),
        mock.patch("plane.app.views.project.member.project_add_user_email.delay"),
    ):
        yield


@pytest.fixture
def brand_project(workspace, create_user):
    apply_brand_roster(workspace.id, [{"brandId": KFC, "name": "KFC", "status": "active"}], authoritative=True)
    project = ZilBrandProject.objects.get(zil_brand_id=KFC).project
    # the workspace admin of the fixtures joins it, like a director would
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    return project


@pytest.fixture
def agent(workspace):
    user = User.objects.create(email="ada@agents.zil", username="ada", is_bot=True, bot_type=BotTypeEnum.ZIL_AGENT)
    WorkspaceMember.objects.create(workspace=workspace, member=user, role=15)
    return user


@pytest.fixture
def operator(workspace):
    user = User.objects.create(email="ana@zil.global", username="ana")
    WorkspaceMember.objects.create(workspace=workspace, member=user, role=15)
    return user


def project_url(workspace, project, suffix=""):
    return f"/api/workspaces/{workspace.slug}/projects/{project.id}/{suffix}"


@pytest.mark.contract
class TestZilProjectSettings:
    @pytest.mark.django_db
    def test_a_brand_project_can_be_renamed_with_an_apostrophe(self, session_client, workspace, brand_project):
        response = session_client.patch(project_url(workspace, brand_project), {"name": "Wendy's"}, format="json")
        assert response.status_code == status.HTTP_200_OK, response.data
        brand_project.refresh_from_db()
        assert brand_project.name == "Wendy's"

    @pytest.mark.django_db
    def test_other_projects_keep_plane_name_rules(self, session_client, workspace):
        created = session_client.post(
            f"/api/workspaces/{workspace.slug}/projects/", {"name": "Interno", "identifier": "INT"}, format="json"
        )
        response = session_client.patch(
            f"/api/workspaces/{workspace.slug}/projects/{created.data['id']}/", {"name": "Wendy's"}, format="json"
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.django_db
    def test_a_brand_project_cannot_be_made_public(self, session_client, workspace, brand_project):
        response = session_client.patch(project_url(workspace, brand_project), {"network": 2}, format="json")
        assert response.status_code == status.HTTP_409_CONFLICT and response.data["code"] == "ZIL_MANAGED"
        brand_project.refresh_from_db()
        assert brand_project.network == 0

    @pytest.mark.django_db
    def test_put_cannot_make_it_public_either(self, session_client, workspace, brand_project):
        response = session_client.put(project_url(workspace, brand_project), {"network": 2}, format="json")
        assert response.status_code == status.HTTP_409_CONFLICT
        brand_project.refresh_from_db()
        assert brand_project.network == 0

    @pytest.mark.django_db
    def test_a_brand_project_keeps_its_identifier(self, session_client, workspace, brand_project):
        response = session_client.patch(project_url(workspace, brand_project), {"identifier": "OTRO"}, format="json")
        assert response.status_code == status.HTTP_409_CONFLICT

    @pytest.mark.django_db
    def test_a_brand_project_cannot_be_archived_or_restored_by_hand(self, session_client, workspace, brand_project):
        # Zil archives it when the brand leaves and restores it when it comes back
        response = session_client.post(project_url(workspace, brand_project, "archive/"))
        assert response.status_code == status.HTTP_409_CONFLICT and response.data["code"] == "ZIL_MANAGED"
        brand_project.refresh_from_db()
        assert brand_project.archived_at is None

        Project.objects.filter(pk=brand_project.pk).update(archived_at=timezone.now())
        response = session_client.delete(project_url(workspace, brand_project, "archive/"))
        assert response.status_code == status.HTTP_409_CONFLICT
        brand_project.refresh_from_db()
        assert brand_project.archived_at is not None

    @pytest.mark.django_db
    def test_the_migration_project_cannot_be_deleted_or_archived(self, session_client, workspace, create_user):
        migration = ensure_migration_project(workspace)
        assert ProjectMember.objects.filter(project=migration, member=create_user, is_active=True).exists()
        assert session_client.delete(project_url(workspace, migration)).status_code == status.HTTP_409_CONFLICT
        assert session_client.post(project_url(workspace, migration, "archive/")).status_code == 409
        assert Project.objects.filter(pk=migration.pk, archived_at__isnull=True).exists()

    @pytest.mark.django_db
    def test_other_projects_still_archive(self, session_client, workspace, create_user):
        project = Project.objects.create(workspace=workspace, name="Interno", identifier="INT")
        ProjectMember.objects.create(project=project, member=create_user, role=20)
        assert session_client.post(project_url(workspace, project, "archive/")).status_code == status.HTTP_200_OK

    @pytest.mark.django_db
    def test_a_brand_project_cannot_be_deleted_in_ops(self, session_client, workspace, brand_project):
        response = session_client.delete(project_url(workspace, brand_project))
        assert response.status_code == status.HTTP_409_CONFLICT
        assert Project.objects.filter(pk=brand_project.pk).exists()


@pytest.mark.contract
class TestZilProjectMembership:
    @pytest.mark.django_db
    def test_people_cannot_be_added_by_hand(self, session_client, workspace, brand_project, operator):
        response = session_client.post(
            project_url(workspace, brand_project, "members/"),
            {"members": [{"member_id": str(operator.id), "role": 15}]},
            format="json",
        )
        assert response.status_code == status.HTTP_409_CONFLICT
        assert not ProjectMember.objects.filter(project=brand_project, member=operator).exists()

    @pytest.mark.django_db
    def test_nobody_is_invited(self, session_client, workspace, brand_project):
        response = session_client.post(
            project_url(workspace, brand_project, "invitations/"),
            {"emails": [{"email": "x@zil.global", "role": 15}]},
            format="json",
        )
        assert response.status_code == status.HTTP_409_CONFLICT

    @pytest.mark.django_db
    def test_a_member_of_the_team_cannot_be_removed_or_changed(
        self, session_client, workspace, brand_project, operator
    ):
        apply_brand_roster(
            workspace.id,
            [{"brandId": KFC, "name": "KFC", "members": [{"email": operator.email}], "membersAuthoritative": True}],
            authoritative=True,
        )
        membership = ProjectMember.objects.get(project=brand_project, member=operator)
        assert (
            session_client.patch(
                project_url(workspace, brand_project, f"members/{membership.id}/"), {"role": 5}, format="json"
            ).status_code
            == status.HTTP_409_CONFLICT
        )
        assert (
            session_client.delete(project_url(workspace, brand_project, f"members/{membership.id}/")).status_code
            == status.HTTP_409_CONFLICT
        )
        membership.refresh_from_db()
        assert membership.is_active and membership.role == 15

    @pytest.mark.django_db
    def test_an_agent_joins_a_brand_only_when_someone_adds_it(self, session_client, workspace, brand_project, agent):
        sync_zil_agent_project_memberships(agent)
        assert not ProjectMember.objects.filter(project=brand_project, member=agent, is_active=True).exists()

        response = session_client.post(
            project_url(workspace, brand_project, "members/"),
            {"members": [{"member_id": str(agent.id), "role": 15}]},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.data

        # resyncing the agent keeps the brand it was added to
        sync_zil_agent_project_memberships(agent)
        assert ProjectMember.objects.filter(project=brand_project, member=agent, is_active=True).exists()

    @pytest.mark.django_db
    def test_other_projects_still_get_every_agent(self, workspace, agent):
        project = Project.objects.create(workspace=workspace, name="Interno", identifier="INT")
        sync_zil_agent_project_memberships(agent)
        assert ProjectMember.objects.filter(project=project, member=agent, is_active=True).exists()

    @pytest.mark.django_db
    def test_a_director_who_joined_can_leave(self, session_client, workspace, brand_project, create_user):
        response = session_client.post(project_url(workspace, brand_project, "members/leave/"))
        assert response.status_code == status.HTTP_204_NO_CONTENT

    @pytest.mark.django_db
    def test_the_public_api_refuses_the_same(self, workspace, brand_project, operator, create_user):
        from plane.db.models.api import APIToken

        token = APIToken.objects.create(user=create_user, label="t", token="brand-guard-token")
        client = APIClient()
        client.credentials(HTTP_X_API_KEY=token.token)
        base = f"/api/v1/workspaces/{workspace.slug}/projects/{brand_project.id}/"
        assert client.patch(base, {"network": 2}, format="json").status_code == status.HTTP_409_CONFLICT
        assert client.post(base + "archive/").status_code == status.HTTP_409_CONFLICT
        assert client.delete(base + "archive/").status_code == status.HTTP_409_CONFLICT
        brand_project.refresh_from_db()
        assert brand_project.archived_at is None
        assert (
            client.post(base + "project-members/", {"member": str(operator.id), "role": 15}, format="json").status_code
            == status.HTTP_409_CONFLICT
        )
