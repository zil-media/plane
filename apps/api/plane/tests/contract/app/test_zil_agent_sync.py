# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from unittest import mock

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from plane.db.models import APIToken, BotTypeEnum, User, UserNotificationPreference, Workspace, WorkspaceMember

URL = "/api/zil/sync/agent/"
AGENT_EMAIL = "ada.agent@zil.global"


@pytest.fixture
def zil_env():
    with mock.patch.dict("os.environ", {"ZIL_SERVICE_SECRET": "secret"}):
        yield


@pytest.fixture
def service_client(api_client, zil_env):
    api_client.credentials(HTTP_X_ZIL_SERVICE_KEY="secret")
    return api_client


@pytest.fixture
def other_workspace(create_user):
    ws = Workspace.objects.create(name="Other", owner=create_user, slug="other-ws")
    WorkspaceMember.objects.create(workspace=ws, member=create_user, role=20)
    return ws


def _body(workspace, **extra):
    return {
        "email": AGENT_EMAIL,
        "name": "Ada",
        "workspaces": [{"slug": workspace.slug, "name": workspace.name, "role": 15, "is_owner": True}],
        **extra,
    }


def _projects_status(workspace, token):
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=token)
    return client.get(f"/api/v1/workspaces/{workspace.slug}/projects/").status_code


# APIKeyAuthentication sets no WWW-Authenticate header, so DRF renders a
# rejected key as 403 rather than 401.
REJECTED = (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)


@pytest.mark.contract
class TestZilAgentSync:
    @pytest.mark.django_db
    def test_requires_service_key(self, api_client, workspace, zil_env):
        response = api_client.post(URL, _body(workspace), format="json")
        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)
        assert not User.objects.filter(email=AGENT_EMAIL).exists()

    @pytest.mark.django_db
    def test_create_provisions_bot_membership_and_working_token(self, service_client, workspace):
        response = service_client.post(URL, _body(workspace), format="json")

        assert response.status_code == status.HTTP_200_OK
        assert response.data["created"] is True
        assert response.data["email"] == AGENT_EMAIL
        assert response.data["workspaces"] == [workspace.slug]
        token = response.data["token"]
        assert token

        agent = User.objects.get(email=AGENT_EMAIL)
        assert str(agent.id) == response.data["user_id"]
        assert agent.is_bot and agent.bot_type == BotTypeEnum.ZIL_AGENT
        assert agent.is_password_autoset and not agent.has_usable_password()
        assert agent.display_name == "Ada" and agent.first_name == "Ada"
        wm = WorkspaceMember.objects.get(workspace=workspace, member=agent)
        assert wm.is_active and wm.role == 15
        # An agent never owns a workspace even if the payload says is_owner.
        workspace.refresh_from_db()
        assert workspace.owner_id != agent.id
        api_token = APIToken.objects.get(token=token)
        assert api_token.user_id == agent.id and api_token.user_type == 1 and api_token.workspace_id is None
        assert api_token.label == "zil-agent"
        # No notification emails: an all-off preference row exists.
        pref = UserNotificationPreference.objects.get(user=agent)
        assert not any([pref.property_change, pref.state_change, pref.comment, pref.mention, pref.issue_completed])

        assert _projects_status(workspace, token) == status.HTTP_200_OK

    @pytest.mark.django_db
    def test_second_call_without_rotate_returns_no_token(self, service_client, workspace):
        first = service_client.post(URL, _body(workspace), format="json")
        second = service_client.post(URL, _body(workspace, name="Ada Lovelace"), format="json")

        assert second.status_code == status.HTTP_200_OK
        assert second.data["created"] is False
        assert second.data["token"] is None
        assert second.data["user_id"] == first.data["user_id"]
        assert User.objects.get(email=AGENT_EMAIL).display_name == "Ada Lovelace"
        assert _projects_status(workspace, first.data["token"]) == status.HTTP_200_OK

    @pytest.mark.django_db
    def test_rotate_issues_new_token_and_rejects_old(self, service_client, workspace):
        old = service_client.post(URL, _body(workspace), format="json").data["token"]
        response = service_client.post(URL, _body(workspace, rotate_token=True), format="json")

        new = response.data["token"]
        assert new and new != old
        assert _projects_status(workspace, old) in REJECTED
        assert _projects_status(workspace, new) == status.HTTP_200_OK

    @pytest.mark.django_db
    def test_membership_list_is_authoritative(self, service_client, workspace, other_workspace):
        service_client.post(URL, _body(workspace), format="json")
        response = service_client.post(
            URL,
            {"email": AGENT_EMAIL, "name": "Ada", "workspaces": [{"slug": other_workspace.slug, "role": 20}]},
            format="json",
        )

        assert response.data["workspaces"] == [other_workspace.slug]
        agent = User.objects.get(email=AGENT_EMAIL)
        assert not WorkspaceMember.objects.get(workspace=workspace, member=agent).is_active
        assert WorkspaceMember.objects.get(workspace=other_workspace, member=agent).role == 20

    @pytest.mark.django_db
    def test_human_email_conflicts(self, service_client, workspace, create_user):
        response = service_client.post(URL, {**_body(workspace), "email": create_user.email}, format="json")

        assert response.status_code == status.HTTP_409_CONFLICT
        create_user.refresh_from_db()
        assert not create_user.is_bot
        assert not APIToken.objects.filter(user=create_user).exists()

    @pytest.mark.django_db
    def test_revoke_then_reissue(self, service_client, workspace):
        token = service_client.post(URL, _body(workspace), format="json").data["token"]
        # Revoke, exactly as the leads side sends it.
        response = service_client.post(
            URL, {"email": AGENT_EMAIL, "name": "Ada", "suspended": True, "workspaces": []}, format="json"
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data["suspended"] is True and response.data["token"] is None
        assert response.data["workspaces"] == []
        agent = User.objects.get(email=AGENT_EMAIL)
        assert not agent.is_active
        assert not WorkspaceMember.objects.filter(member=agent, is_active=True).exists()
        assert not APIToken.objects.filter(token=token, is_active=True).exists()
        assert _projects_status(workspace, token) in REJECTED

        # Re-issue: reactivates the bot, restores memberships, mints a fresh token.
        revived = service_client.post(URL, _body(workspace, suspended=False, rotate_token=True), format="json")
        assert revived.status_code == status.HTTP_200_OK
        assert revived.data["created"] is False
        assert revived.data["user_id"] == str(agent.id)
        assert revived.data["workspaces"] == [workspace.slug]
        assert User.objects.get(email=AGENT_EMAIL).is_active
        assert revived.data["token"] and revived.data["token"] != token
        assert _projects_status(workspace, revived.data["token"]) == status.HTTP_200_OK
        assert _projects_status(workspace, token) in REJECTED

    @pytest.mark.django_db
    def test_agent_is_skipped_by_user_sync(self, service_client, workspace, other_workspace):
        service_client.post(URL, _body(workspace), format="json")
        response = service_client.post(
            "/api/zil/sync/user/",
            {"email": AGENT_EMAIL, "workspaces": [{"slug": other_workspace.slug}], "authoritative": True},
            format="json",
        )

        assert response.data["status"] == "skipped"
        assert not WorkspaceMember.objects.filter(member__email=AGENT_EMAIL, workspace=other_workspace).exists()
