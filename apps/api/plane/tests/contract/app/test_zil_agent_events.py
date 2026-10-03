# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Ops → Zil Workspace events when a person mentions or assigns a Zil AI agent."""

import json
from unittest import mock

import pytest
from rest_framework import status

from plane.bgtasks.issue_activities_task import issue_activity
from plane.bgtasks.zil_agent_events_task import deliver_zil_agent_event
from plane.db.models import (
    BotTypeEnum,
    Issue,
    IssueComment,
    Project,
    ProjectMember,
    User,
    WorkspaceMember,
)

EPOCH = 1700000000
ZIL_ENV = {"ZIL_BASE_URL": "https://zil.example/", "ZIL_SERVICE_SECRET": "secret"}


def mention(user):
    return f'<mention-component entity_identifier="{user.id}" entity_name="user_mention"></mention-component>'


@pytest.fixture
def zil_env():
    with mock.patch.dict("os.environ", ZIL_ENV):
        yield


@pytest.fixture
def delay():
    with mock.patch("plane.bgtasks.zil_agent_events_task.deliver_zil_agent_event.delay") as m:
        yield m


@pytest.fixture
def project(workspace, create_user):
    project = Project.objects.create(name="Mercury", identifier="MER", workspace=workspace)
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    return project


def _bot(workspace, project, email, bot_type):
    bot = User.objects.create(
        email=email, username=email, display_name=email.split(".")[0].title(), is_bot=True, bot_type=bot_type
    )
    WorkspaceMember.objects.create(workspace=workspace, member=bot, role=15)
    ProjectMember.objects.create(project=project, member=bot, role=15)
    return bot


@pytest.fixture
def agent(workspace, project):
    return _bot(workspace, project, "ada.agent@zil.global", BotTypeEnum.ZIL_AGENT)


@pytest.fixture
def issue(project, create_user):
    return Issue.objects.create(
        name="Fix login", project=project, description_html="<p>Login is broken</p>", created_by=create_user
    )


def _comment(issue, actor, html):
    comment = IssueComment.objects.create(issue=issue, project=issue.project, comment_html=html, actor=actor)
    issue_activity(
        type="comment.activity.created",
        requested_data=json.dumps({"id": str(comment.id), "comment_html": html}),
        current_instance=None,
        issue_id=str(issue.id),
        actor_id=str(actor.id),
        project_id=str(issue.project_id),
        epoch=EPOCH,
    )
    return comment


def _update_issue(issue, actor, requested, current):
    issue_activity(
        type="issue.activity.updated",
        requested_data=json.dumps(requested),
        current_instance=json.dumps(current),
        issue_id=str(issue.id),
        actor_id=str(actor.id),
        project_id=str(issue.project_id),
        epoch=EPOCH,
    )


@pytest.mark.contract
class TestZilAgentEvents:
    @pytest.mark.django_db
    def test_comment_mention_by_human_delivers_one_event(self, zil_env, delay, issue, agent, create_user, settings):
        settings.WEB_URL = "https://ops.example"
        comment = _comment(issue, create_user, f"<p>{mention(agent)} please check the logs</p>")

        assert delay.call_count == 1
        payload = delay.call_args.args[0]
        assert payload["eventId"].startswith(f"ops:mention:comment:{comment.id}:")
        assert payload["eventId"].endswith(f":{agent.id}")
        assert payload["actor"]["email"] == create_user.email and payload["actor"]["name"]
        assert payload == {
            "eventId": payload["eventId"],
            "kind": "mention",
            "agentEmail": "ada.agent@zil.global",
            "actor": payload["actor"],
            "workspaceSlug": issue.workspace.slug,
            "projectId": str(issue.project_id),
            "projectIdentifier": "MER",
            "issueId": str(issue.id),
            "issueSequence": issue.sequence_id,
            "issueName": "Fix login",
            "commentId": str(comment.id),
            "text": "@Ada please check the logs",
            "url": f"https://ops.example/test-workspace/projects/{issue.project_id}/issues/{issue.id}",
        }

    @pytest.mark.django_db
    def test_mention_by_agent_is_ignored(self, zil_env, delay, issue, agent, workspace, project):
        other_agent = _bot(workspace, project, "iris.agent@zil.global", BotTypeEnum.ZIL_AGENT)
        _comment(issue, other_agent, f"<p>{mention(agent)} over to you</p>")

        delay.assert_not_called()

    @pytest.mark.django_db
    def test_non_agent_bot_is_ignored(self, zil_env, delay, issue, workspace, project, create_user):
        seed_bot = _bot(workspace, project, "seed.bot@plane.so", BotTypeEnum.WORKSPACE_SEED)
        _comment(issue, create_user, f"<p>{mention(seed_bot)} hi</p>")
        _update_issue(issue, create_user, {"assignee_ids": [str(seed_bot.id)]}, {"assignee_ids": []})

        delay.assert_not_called()

    @pytest.mark.django_db
    def test_assignment_delivers_one_event(self, zil_env, delay, issue, agent, create_user):
        _update_issue(issue, create_user, {"assignee_ids": [str(agent.id)]}, {"assignee_ids": []})

        assert delay.call_count == 1
        payload = delay.call_args.args[0]
        assert payload["kind"] == "assigned"
        assert payload["agentEmail"] == agent.email
        assert payload["commentId"] is None
        assert payload["text"] == "Login is broken"

    @pytest.mark.django_db
    def test_description_mention_only_when_new(self, zil_env, delay, issue, agent, create_user):
        html = f"<p>{mention(agent)} take a look</p>"
        _update_issue(issue, create_user, {"description_html": html}, {"description_html": "<p>old</p>"})
        assert delay.call_count == 1
        assert delay.call_args.args[0]["kind"] == "mention"
        assert delay.call_args.args[0]["commentId"] is None

        # Saving again with the same mention already present → nothing new.
        _update_issue(issue, create_user, {"description_html": html + "<p>more</p>"}, {"description_html": html})
        assert delay.call_count == 1

    @pytest.mark.django_db
    def test_comment_edit_without_new_mention_is_ignored(self, zil_env, delay, issue, agent, create_user):
        html = f"<p>{mention(agent)} check</p>"
        comment = _comment(issue, create_user, html)
        assert delay.call_count == 1

        issue_activity(
            type="comment.activity.updated",
            requested_data=json.dumps({"comment_html": html + "<p>edit</p>"}),
            current_instance=json.dumps({"id": str(comment.id), "comment_html": html}),
            issue_id=str(issue.id),
            actor_id=str(create_user.id),
            project_id=str(issue.project_id),
            epoch=EPOCH + 1,
        )
        assert delay.call_count == 1

    @pytest.mark.django_db
    def test_not_configured_sends_nothing(self, delay, issue, agent, create_user):
        with mock.patch.dict("os.environ", {"ZIL_BASE_URL": "", "ZIL_SERVICE_SECRET": ""}):
            _comment(issue, create_user, f"<p>{mention(agent)}</p>")
        delay.assert_not_called()

    def test_delivery_posts_to_workspace_with_service_key(self, zil_env):
        with mock.patch("plane.bgtasks.zil_agent_events_task.requests.post") as post:
            post.return_value.status_code = 202
            deliver_zil_agent_event.apply(args=[{"eventId": "e1"}])

        post.assert_called_once()
        assert post.call_args.args[0] == "https://zil.example/api/agent/ai-agents/ops-events"
        assert post.call_args.kwargs["headers"] == {"X-Zil-Service-Key": "secret"}
        assert post.call_args.kwargs["json"] == {"eventId": "e1"}


@pytest.mark.contract
class TestZilAgentMembership:
    @pytest.mark.django_db
    def test_agent_listed_as_project_member_other_bots_not(self, session_client, workspace, project, agent):
        seed_bot = _bot(workspace, project, "seed.bot@plane.so", BotTypeEnum.WORKSPACE_SEED)
        response = session_client.get(f"/api/workspaces/{workspace.slug}/projects/{project.id}/members/")

        assert response.status_code == status.HTTP_200_OK
        members = {str(m["member"]) for m in response.data}
        assert str(agent.id) in members
        assert str(seed_bot.id) not in members

    @pytest.mark.django_db
    def test_agent_is_mention_suggestion(self, session_client, workspace, project, agent):
        response = session_client.get(
            f"/api/workspaces/{workspace.slug}/entity-search/",
            {"query_type": "user_mention", "query": "Ada", "project_id": str(project.id)},
        )

        assert response.status_code == status.HTTP_200_OK
        assert [str(u["member__id"]) for u in response.data["user_mention"]] == [str(agent.id)]

    @pytest.mark.django_db
    def test_sync_adds_agent_to_existing_projects(self, api_client, workspace, project):
        api_client.credentials(HTTP_X_ZIL_SERVICE_KEY="secret")
        body = {
            "email": "nora.agent@zil.global",
            "name": "Nora",
            "workspaces": [{"slug": workspace.slug, "name": workspace.name, "role": 20}],
        }
        with mock.patch.dict("os.environ", {"ZIL_SERVICE_SECRET": "secret"}):
            assert api_client.post("/api/zil/sync/agent/", body, format="json").status_code == status.HTTP_200_OK
            nora = User.objects.get(email="nora.agent@zil.global")
            pm = ProjectMember.objects.get(project=project, member=nora)
            assert pm.is_active and pm.role == 15

            body["workspaces"] = []
            body["suspended"] = True
            api_client.post("/api/zil/sync/agent/", body, format="json")
        assert not ProjectMember.objects.get(project=project, member=nora).is_active

    @pytest.mark.django_db
    def test_new_project_includes_workspace_agents(self, session_client, workspace, project, agent):
        response = session_client.post(
            f"/api/workspaces/{workspace.slug}/projects/", {"name": "Venus", "identifier": "VEN"}, format="json"
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert ProjectMember.objects.filter(project_id=response.data["id"], member=agent, is_active=True).exists()
