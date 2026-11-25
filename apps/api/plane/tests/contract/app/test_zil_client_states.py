# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import pytest
from rest_framework import status

from plane.db.models import (
    AgentFeatureFlag,
    Issue,
    Project,
    ProjectMember,
    State,
    WorkspaceMember,
    ZilBrandProject,
    ZilClientStatesTemplate,
)
from plane.utils.zil_brand_projects import apply_brand_roster, ensure_migration_project
from plane.utils.zil_client_states import apply_client_states

KFC = "0123456789abcdef0123c001"
WENDYS = "0123456789abcdef0123c002"
NEW = "0123456789abcdef0123c003"

MODEL_STATES = [
    ("Pendiente", "unstarted", "#AAAAAA", True),
    ("En proceso", "started", "#F59E0B", False),
    ("En revisión", "started", "#3F76FF", False),
    ("Finalizado", "completed", "#46A758", False),
]


@pytest.fixture
def flag(db):
    return AgentFeatureFlag.objects.create(key="clientStatesTemplate", enabled=True)


@pytest.fixture
def team_project(workspace, create_user):
    project = Project.objects.create(name="Team Meraki", identifier="TEAM", workspace=workspace)
    ProjectMember.objects.create(project=project, member=create_user, role=20, workspace=workspace)
    for index, (name, group, color, default) in enumerate(MODEL_STATES):
        State.objects.bulk_create(
            [
                State(
                    name=name,
                    group=group,
                    color=color,
                    default=default,
                    sequence=(index + 1) * 1000,
                    project=project,
                    workspace=workspace,
                )
            ]
        )
    return project


@pytest.fixture
def clients(workspace):
    apply_brand_roster(
        workspace.id,
        [
            {"brandId": KFC, "name": "KFC", "status": "active"},
            {"brandId": WENDYS, "name": "Wendys", "status": "active"},
        ],
        authoritative=True,
    )
    return [m.project for m in ZilBrandProject.objects.filter(kind="brand").order_by("created_at")]


def _issue(project, state_name, name="x"):
    state = State.objects.get(project=project, name=state_name)
    return Issue.objects.create(name=name, project=project, workspace_id=project.workspace_id, state=state)


def _names(project):
    return list(State.objects.filter(project=project).order_by("sequence").values_list("name", flat=True))


def _url(workspace):
    return f"/api/workspaces/{workspace.slug}/zil-client-states/"


@pytest.mark.contract
class TestApplyClientStates:
    @pytest.mark.django_db
    def test_clients_get_the_model_states_and_keep_every_work_item(self, workspace, team_project, clients):
        kfc = clients[0]
        backlog = _issue(kfc, "Backlog", "a")
        todo = _issue(kfc, "Todo", "b")
        doing = _issue(kfc, "In Progress", "c")
        done = _issue(kfc, "Done", "d")
        cancelled = _issue(kfc, "Cancelled", "e")
        total = Issue.objects.filter(project=kfc).count()

        stats = apply_client_states(workspace.id, team_project)

        assert stats["updated"] == 2 and stats["failed"] == []
        # the model has no cancelled state: cancelled work has nowhere of its kind to go and stays
        assert _names(kfc) == ["Pendiente", "En proceso", "En revisión", "Finalizado", "Cancelled"]
        assert Issue.objects.filter(project=kfc).count() == total
        for issue, expected in (
            (backlog, "Pendiente"),
            (todo, "Pendiente"),
            (doing, "En proceso"),
            (done, "Finalizado"),
        ):
            issue.refresh_from_db()
            assert issue.state.name == expected
        cancelled.refresh_from_db()
        assert cancelled.state.name == "Cancelled"
        assert State.objects.get(project=kfc, default=True).name == "Pendiente"
        assert State.triage_objects.filter(project=kfc).exists()
        assert stats["work_items_moved"] == 4

    @pytest.mark.django_db
    def test_empty_unmatched_states_are_removed(self, workspace, team_project, clients):
        apply_client_states(workspace.id, team_project)
        wendys = clients[1]
        assert _names(wendys) == ["Pendiente", "En proceso", "En revisión", "Finalizado", "Cancelled"]
        assert not State.objects.filter(project=wendys, name="Backlog").exists()

    @pytest.mark.django_db
    def test_a_state_named_like_the_model_is_reused(self, workspace, team_project, clients):
        kfc = clients[0]
        existing = State.objects.create(
            name="en proceso", group="backlog", color="#000", project=kfc, workspace=workspace
        )
        issue = Issue.objects.create(name="x", project=kfc, workspace=workspace, state=existing)

        apply_client_states(workspace.id, team_project)

        existing.refresh_from_db()
        assert existing.deleted_at is None
        assert (existing.name, existing.group, existing.color) == ("En proceso", "started", "#F59E0B")
        issue.refresh_from_db()
        assert issue.state_id == existing.id

    @pytest.mark.django_db
    def test_applying_twice_changes_nothing(self, workspace, team_project, clients):
        _issue(clients[0], "In Progress")
        apply_client_states(workspace.id, team_project)
        before = list(State.all_state_objects.filter(project=clients[0]).values_list("id", "name", "deleted_at"))

        stats = apply_client_states(workspace.id, team_project)

        assert stats["work_items_moved"] == 0
        assert (
            list(State.all_state_objects.filter(project=clients[0]).values_list("id", "name", "deleted_at")) == before
        )

    @pytest.mark.django_db
    def test_team_and_migration_projects_are_untouched(self, workspace, team_project, clients):
        other = Project.objects.create(name="Interno", identifier="INT", workspace=workspace)
        State.objects.create(name="Backlog", group="backlog", color="#000", project=other, workspace=workspace)
        migration = ensure_migration_project(workspace)
        migration_states = _names(migration)

        apply_client_states(workspace.id, team_project)

        assert _names(other) == ["Backlog"]
        assert _names(migration) == migration_states
        assert _names(team_project) == [name for name, *_ in MODEL_STATES]


@pytest.mark.contract
class TestNewClientStates:
    @pytest.mark.django_db
    def test_a_new_client_is_born_with_the_model_states(self, workspace, team_project, flag):
        ZilClientStatesTemplate.objects.create(workspace=workspace, template_project=team_project)

        apply_brand_roster(workspace.id, [{"brandId": NEW, "name": "Nuevo", "status": "active"}], authoritative=False)

        project = ZilBrandProject.objects.get(zil_brand_id=NEW).project
        assert _names(project) == [name for name, *_ in MODEL_STATES]
        assert State.objects.get(project=project, default=True).name == "Pendiente"
        assert State.triage_objects.filter(project=project).count() == 1

    @pytest.mark.django_db
    def test_without_the_flag_new_clients_keep_the_usual_states(self, workspace, team_project):
        ZilClientStatesTemplate.objects.create(workspace=workspace, template_project=team_project)

        apply_brand_roster(workspace.id, [{"brandId": NEW, "name": "Nuevo", "status": "active"}], authoritative=False)

        project = ZilBrandProject.objects.get(zil_brand_id=NEW).project
        assert "Backlog" in _names(project)

    @pytest.mark.django_db
    def test_the_migration_project_keeps_the_usual_states(self, workspace, team_project, flag):
        ZilClientStatesTemplate.objects.create(workspace=workspace, template_project=team_project)
        assert "Backlog" in _names(ensure_migration_project(workspace))


@pytest.mark.contract
class TestClientStatesEndpoint:
    @pytest.mark.django_db
    def test_flag_off_is_404(self, session_client, workspace, team_project):
        assert session_client.get(_url(workspace)).status_code == status.HTTP_404_NOT_FOUND
        response = session_client.put(_url(workspace), {"template_project_id": str(team_project.id)}, format="json")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.django_db
    def test_member_is_forbidden(self, session_client, workspace, create_user, team_project, flag):
        WorkspaceMember.objects.filter(member=create_user, workspace=workspace).update(role=15)
        assert session_client.get(_url(workspace)).status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.django_db
    def test_get_lists_team_projects_and_previews(self, session_client, workspace, team_project, clients, flag):
        _issue(clients[0], "In Progress")

        response = session_client.get(_url(workspace), {"template_project_id": str(team_project.id)})

        assert response.status_code == status.HTTP_200_OK
        assert [p["name"] for p in response.data["projects"]] == ["Team Meraki"]
        assert response.data["preview"] == {"clients": 2, "work_items_to_move": 1}
        assert response.data["template_project_id"] is None

    @pytest.mark.django_db
    def test_put_saves_and_applies(self, session_client, workspace, team_project, clients, flag):
        response = session_client.put(
            _url(workspace), {"template_project_id": str(team_project.id), "apply": True}, format="json"
        )

        assert response.status_code == status.HTTP_200_OK, response.data
        assert response.data["result"]["updated"] == 2
        template = ZilClientStatesTemplate.objects.get(workspace=workspace)
        assert template.template_project_id == team_project.id and template.applied_at is not None
        assert "Pendiente" in _names(clients[0])

    @pytest.mark.django_db
    def test_a_client_cannot_be_the_model(self, session_client, workspace, team_project, clients, flag):
        response = session_client.put(_url(workspace), {"template_project_id": str(clients[0].id)}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        response = session_client.put(_url(workspace), {"template_project_id": "nope"}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
