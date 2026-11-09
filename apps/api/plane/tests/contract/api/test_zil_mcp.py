# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Ops MCP support: API-key page routes, the page search, whoami and the OAuth flow."""

import base64
import hashlib
import secrets
from urllib.parse import parse_qs, urlparse

import pytest
import requests
from unittest import mock
from django.test import Client

from plane.db.models import (
    APIToken,
    McpOAuthGrant,
    Page,
    Project,
    ProjectMember,
    ProjectPage,
    User,
    Workspace,
    WorkspaceMember,
)

BASE = "https://ops.example.com"


@pytest.fixture
def project(db, workspace, create_user):
    project = Project.objects.create(name="Ops", identifier="OPS", workspace=workspace, created_by=create_user)
    ProjectMember.objects.create(project=project, member=create_user, role=20, is_active=True)
    return project


def make_page(project, owner, name="Plan", access=Page.PUBLIC_ACCESS, text="contenido del plan", **extra):
    page = Page.objects.create(
        workspace=project.workspace,
        owned_by=owner,
        name=name,
        access=access,
        description_html=f"<p>{text}</p>",
        **extra,
    )
    ProjectPage.objects.create(page=page, project=project, workspace=project.workspace)
    return page


@pytest.fixture
def other_user(db, workspace, project):
    user = User.objects.create(email="other@plane.so", first_name="Other", username="other")
    ProjectMember.objects.create(project=project, member=user, role=15, is_active=True)
    return user


def pages_url(workspace, project, suffix=""):
    return f"/api/v1/workspaces/{workspace.slug}/projects/{project.id}/pages/{suffix}"


def live_answer(body, status_code=200):
    return mock.Mock(status_code=status_code, json=mock.Mock(return_value=body))


EDITED = {
    "changed": True,
    "summary": ['replaced 1 occurrence of "plan"'],
    "blocks": "aaaaaaaa | contenido del PLAN",
    "total_blocks": 1,
    "applied_to_live_document": False,
    "description_binary": base64.b64encode(b"\x01\x02\x03\x04").decode(),
    "description_html": "<p>contenido del PLAN</p>",
    "description_json": {"type": "doc"},
}


@pytest.fixture
def live_configured(settings):
    settings.LIVE_URL = "http://live:3000/live"
    settings.LIVE_SERVER_SECRET_KEY = "secret"


@pytest.mark.contract
class TestPageBlocks:
    def test_read_sends_the_stored_document_and_reports_edit_rights(
        self, api_key_client, workspace, project, create_user, live_configured
    ):
        page = make_page(project, create_user)
        content = {"content": "#1       | contenido del plan", "total_blocks": 1, "shown_blocks": 1, "offset": 0}
        with mock.patch("plane.utils.page_content.requests.post", return_value=live_answer(content)) as post:
            response = api_key_client.get(pages_url(workspace, project, f"{page.id}/blocks/?limit=5&blocks=aaaa,#2"))
        assert response.status_code == 200
        assert response.data["content"] == content["content"]
        assert response.data["page"]["can_edit"] is True
        url = post.call_args.args[0]
        assert url.endswith(f"/page-content/{page.id}/read/")
        payload = post.call_args.kwargs["json"]
        assert payload["limit"] == 5 and payload["blocks"] == ["aaaa", "#2"]
        assert payload["current_description_html"] == "<p>contenido del plan</p>"
        assert post.call_args.kwargs["headers"] == {"live-server-secret-key": "secret"}

    def test_edit_stores_what_the_live_server_returns(
        self, api_key_client, workspace, project, create_user, live_configured
    ):
        page = make_page(project, create_user)
        ops = [{"op": "replace_text", "find": "plan", "replace": "PLAN"}]
        with mock.patch("plane.utils.page_content.requests.post", return_value=live_answer(EDITED)) as post:
            response = api_key_client.post(
                pages_url(workspace, project, f"{page.id}/edit/"), {"ops": ops}, format="json"
            )
        assert response.status_code == 200, response.data
        assert response.data == {
            "changed": True,
            "summary": EDITED["summary"],
            "blocks": EDITED["blocks"],
            "total_blocks": 1,
        }
        assert post.call_args.kwargs["json"]["ops"] == ops
        page.refresh_from_db()
        assert page.description_html == "<p>contenido del PLAN</p>"
        assert bytes(page.description_binary) == b"\x01\x02\x03\x04"

    def test_rejected_edit_changes_nothing(self, api_key_client, workspace, project, create_user, live_configured):
        page = make_page(project, create_user)
        rejected = live_answer({"message": 'op 1 (delete): Block "ffff" not found.'}, status_code=422)
        with mock.patch("plane.utils.page_content.requests.post", return_value=rejected):
            response = api_key_client.post(
                pages_url(workspace, project, f"{page.id}/edit/"),
                {"ops": [{"op": "delete", "block": "ffff"}]},
                format="json",
            )
        assert response.status_code == 422
        assert "not found" in response.data["error"]
        page.refresh_from_db()
        assert page.description_html == "<p>contenido del plan</p>"

    def test_edit_guards(self, api_client, api_key_client, workspace, project, create_user, live_configured):
        page = make_page(project, create_user)
        assert (
            api_key_client.post(
                pages_url(workspace, project, f"{page.id}/edit/"), {"ops": []}, format="json"
            ).status_code
            == 400
        )

        page.is_locked = True
        page.save()
        with mock.patch("plane.utils.page_content.requests.post") as post:
            locked = api_key_client.post(
                pages_url(workspace, project, f"{page.id}/edit/"),
                {"ops": [{"op": "replace_all", "content": "x"}]},
                format="json",
            )
        assert locked.status_code == 400 and not post.called

        guest = User.objects.create(email="guest@plane.so", username="guest")
        ProjectMember.objects.create(project=project, member=guest, role=5, is_active=True)
        project.guest_view_all_features = True
        project.save()
        page.is_locked = False
        page.save()
        api_client.credentials(HTTP_X_API_KEY=APIToken.objects.create(user=guest, label="g").token)
        forbidden = api_client.post(
            pages_url(workspace, project, f"{page.id}/edit/"),
            {"ops": [{"op": "replace_all", "content": "x"}]},
            format="json",
        )
        assert forbidden.status_code == 403

    def test_live_server_down(self, api_key_client, workspace, project, create_user, live_configured):
        page = make_page(project, create_user)
        with mock.patch("plane.utils.page_content.requests.post", side_effect=requests.ConnectionError("down")):
            response = api_key_client.post(
                pages_url(workspace, project, f"{page.id}/edit/"),
                {"ops": [{"op": "replace_all", "content": "x"}]},
                format="json",
            )
        assert response.status_code == 503


@pytest.mark.contract
class TestPageSearch:
    def test_finds_by_title_and_content_without_leaking_private_pages(
        self, api_key_client, workspace, project, create_user, other_user
    ):
        make_page(project, create_user, name="Presupuesto 2027", text="números")
        make_page(project, create_user, name="Notas", text="hablar del presupuesto con finanzas")
        make_page(project, other_user, name="Presupuesto secreto", access=Page.PRIVATE_ACCESS)

        response = api_key_client.get(f"/api/v1/workspaces/{workspace.slug}/pages/search/?q=presupuesto")
        assert response.status_code == 200
        names = {result["name"] for result in response.data["results"]}
        assert names == {"Presupuesto 2027", "Notas"}
        notes = next(result for result in response.data["results"] if result["name"] == "Notas")
        assert "presupuesto" in notes["snippet"]
        assert notes["project_id"] == str(project.id)


@pytest.mark.contract
class TestWhoAmI:
    def test_reports_user_and_token_workspace(self, api_client, workspace, create_user):
        token = APIToken.objects.create(user=create_user, label="mcp", workspace=workspace)
        api_client.credentials(HTTP_X_API_KEY=token.token)
        response = api_client.get("/api/v1/zil-mcp/whoami/")
        assert response.status_code == 200
        assert response.data["user"]["email"] == create_user.email
        assert response.data["workspace_slug"] == workspace.slug
        assert response.data["workspaces"] == [{"slug": workspace.slug, "name": workspace.name}]

    def test_a_plain_personal_token_may_use_every_workspace(self, api_key_client):
        response = api_key_client.get("/api/v1/zil-mcp/whoami/")
        assert response.status_code == 200
        assert response.data["workspace_slug"] is None
        assert response.data["all_workspaces"] is True


# ─── OAuth ─────────────────────────────────────────────────────────────────────

REDIRECT = "https://claude.ai/api/mcp/auth_callback"


def pkce():
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def register(client, redirect=REDIRECT, name="Claude"):
    return client.post(
        "/auth/mcp/register/",
        data={"redirect_uris": [redirect], "client_name": name, "token_endpoint_auth_method": "none"},
        content_type="application/json",
    )


def authorize(browser, client_id, challenge, state="st4te"):
    """Runs the authorize step with a signed-in browser and returns the code."""
    response = browser.get(
        "/auth/mcp/authorize/",
        {
            "client_id": client_id,
            "redirect_uri": REDIRECT,
            "response_type": "code",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state,
            "resource": f"{BASE}/mcp",
        },
    )
    assert response.status_code == 302
    consent_url = response["Location"]
    assert consent_url.startswith("/auth/mcp/authorize/")
    return consent_url


@pytest.mark.contract
class TestMcpOAuth:
    @pytest.fixture(autouse=True)
    def _public_url(self, settings):
        settings.APP_BASE_URL = BASE
        settings.WEB_URL = BASE

    def test_metadata(self, db):
        response = Client().get("/.well-known/oauth-authorization-server")
        assert response.status_code == 200
        assert response.json()["token_endpoint"] == f"{BASE}/auth/mcp/token/"
        assert Client().get("/.well-known/oauth-authorization-server/mcp").status_code == 200

    def test_register_only_known_destinations(self, db):
        assert register(Client()).status_code == 201
        assert register(Client(), redirect="https://evil.example/cb").status_code == 400
        assert register(Client(), redirect="http://127.0.0.1:33418/callback").status_code == 201

    def test_full_flow_issues_an_api_token_that_works_and_refreshes(self, db, workspace, create_user):
        client_id = register(Client()).json()["client_id"]
        verifier, challenge = pkce()

        anonymous = Client()
        consent_url = authorize(anonymous, client_id, challenge)
        to_login = anonymous.get(consent_url)
        assert to_login.status_code == 302
        assert f"next_path={consent_url}" in to_login["Location"]

        browser = Client()
        browser.force_login(create_user)
        page = browser.get(consent_url)
        assert page.status_code == 200
        assert "Permitir" in page.content.decode()

        decided = browser.post(consent_url, {"decision": "allow", "workspace": workspace.slug})
        assert decided.status_code == 302
        callback = urlparse(decided["Location"])
        query = parse_qs(callback.query)
        assert f"{callback.scheme}://{callback.netloc}{callback.path}" == REDIRECT
        assert query["state"] == ["st4te"] and query["iss"] == [BASE]
        code = query["code"][0]

        server = Client()
        bad = server.post(
            "/auth/mcp/token/",
            {"grant_type": "authorization_code", "client_id": client_id, "code": code, "code_verifier": "wrong"},
        )
        assert bad.status_code == 400 and bad.json()["error"] == "invalid_grant"

        # the failed attempt burned the code: codes are single use
        verifier2, challenge2 = pkce()
        code = parse_qs(
            urlparse(
                browser.post(
                    authorize(browser, client_id, challenge2), {"decision": "allow", "workspace": workspace.slug}
                )["Location"]
            ).query
        )["code"][0]
        token = server.post(
            "/auth/mcp/token/",
            {
                "grant_type": "authorization_code",
                "client_id": client_id,
                "code": code,
                "code_verifier": verifier2,
                "redirect_uri": REDIRECT,
            },
        )
        assert token.status_code == 200, token.content
        body = token.json()
        assert body["token_type"] == "Bearer" and body["expires_in"] == 86400

        api_token = APIToken.objects.get(token=body["access_token"])
        assert api_token.user == create_user and api_token.workspace == workspace
        assert api_token.label == "Claude (conector)"
        me = Client().get("/api/v1/users/me/", HTTP_X_API_KEY=body["access_token"])
        assert me.status_code == 200

        replay = server.post(
            "/auth/mcp/token/",
            {"grant_type": "authorization_code", "client_id": client_id, "code": code, "code_verifier": verifier2},
        )
        assert replay.status_code == 400

        refreshed = server.post(
            "/auth/mcp/token/",
            {"grant_type": "refresh_token", "client_id": client_id, "refresh_token": body["refresh_token"]},
        )
        assert refreshed.status_code == 200
        new_access = refreshed.json()["access_token"]
        assert new_access != body["access_token"]
        assert Client().get("/api/v1/users/me/", HTTP_X_API_KEY=body["access_token"]).status_code in (401, 403)
        assert Client().get("/api/v1/users/me/", HTTP_X_API_KEY=new_access).status_code == 200

        # revoking the token in Ops kills the refresh token too
        APIToken.objects.filter(pk=api_token.pk).update(is_active=False)
        dead = server.post(
            "/auth/mcp/token/",
            {"grant_type": "refresh_token", "client_id": client_id, "refresh_token": body["refresh_token"]},
        )
        assert dead.status_code == 400

    def test_deny_and_reconnect(self, db, workspace, create_user):
        browser = Client()
        browser.force_login(create_user)

        client_id = register(Client()).json()["client_id"]
        _, challenge = pkce()
        denied = browser.post(authorize(browser, client_id, challenge), {"decision": "deny"})
        assert parse_qs(urlparse(denied["Location"]).query)["error"] == ["access_denied"]

        tokens = []
        for _ in range(2):
            client_id = register(Client()).json()["client_id"]
            verifier, challenge = pkce()
            location = browser.post(
                authorize(browser, client_id, challenge), {"decision": "allow", "workspace": workspace.slug}
            )["Location"]
            code = parse_qs(urlparse(location).query)["code"][0]
            tokens.append(
                Client()
                .post(
                    "/auth/mcp/token/",
                    {
                        "grant_type": "authorization_code",
                        "client_id": client_id,
                        "code": code,
                        "code_verifier": verifier,
                    },
                )
                .json()["access_token"]
            )
        # connecting the same app again replaces the previous connection
        assert not APIToken.objects.get(token=tokens[0]).is_active
        assert APIToken.objects.get(token=tokens[1]).is_active
        assert McpOAuthGrant.objects.count() == 2

    def test_rejects_unknown_client_and_foreign_redirect(self, db, create_user):
        browser = Client()
        browser.force_login(create_user)
        _, challenge = pkce()
        unknown = browser.get("/auth/mcp/authorize/", {"client_id": "nope", "response_type": "code"})
        assert unknown.status_code == 400
        client_id = register(Client()).json()["client_id"]
        foreign = browser.get(
            "/auth/mcp/authorize/",
            {
                "client_id": client_id,
                "redirect_uri": "https://claude.ai/other",
                "response_type": "code",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
        )
        assert foreign.status_code == 400


@pytest.mark.contract
class TestMcpOAuthAllWorkspaces:
    @pytest.fixture(autouse=True)
    def _public_url(self, settings):
        settings.APP_BASE_URL = BASE
        settings.WEB_URL = BASE

    @pytest.fixture
    def second_workspace(self, db, create_user):
        other = Workspace.objects.create(name="Meraki", owner=create_user, slug="meraki")
        WorkspaceMember.objects.create(workspace=other, member=create_user, role=20)
        return other

    def connect(self, browser, form):
        client_id = register(Client()).json()["client_id"]
        verifier, challenge = pkce()
        location = browser.post(authorize(browser, client_id, challenge), {"decision": "allow", **form})["Location"]
        code = parse_qs(urlparse(location).query)["code"][0]
        body = (
            Client()
            .post(
                "/auth/mcp/token/",
                {"grant_type": "authorization_code", "client_id": client_id, "code": code, "code_verifier": verifier},
            )
            .json()
        )
        return client_id, body

    def whoami(self, access_token):
        return Client().get("/api/v1/zil-mcp/whoami/", HTTP_X_API_KEY=access_token).json()

    def test_consent_offers_every_workspace_only_with_more_than_one(self, db, workspace, create_user):
        browser = Client()
        browser.force_login(create_user)
        client_id = register(Client()).json()["client_id"]
        _, challenge = pkce()
        single = browser.get(authorize(browser, client_id, challenge)).content.decode()
        assert 'name="all_workspaces"' not in single

        other = Workspace.objects.create(name="Meraki", owner=create_user, slug="meraki")
        WorkspaceMember.objects.create(workspace=other, member=create_user, role=20)
        _, challenge = pkce()
        several = browser.get(authorize(browser, client_id, challenge)).content.decode()
        assert 'name="all_workspaces"' in several
        assert "mis otros espacios (1)" in several

    def test_one_workspace_by_default(self, db, workspace, second_workspace, create_user):
        browser = Client()
        browser.force_login(create_user)
        _, body = self.connect(browser, {"workspace": second_workspace.slug})
        me = self.whoami(body["access_token"])
        assert me["workspace_slug"] == second_workspace.slug
        assert me["all_workspaces"] is False
        assert not McpOAuthGrant.objects.get().all_workspaces

    def test_every_workspace_keeps_the_main_one_and_survives_refresh(
        self, db, workspace, second_workspace, create_user
    ):
        browser = Client()
        browser.force_login(create_user)
        client_id, body = self.connect(browser, {"workspace": second_workspace.slug, "all_workspaces": "on"})
        me = self.whoami(body["access_token"])
        assert me["workspace_slug"] == second_workspace.slug
        assert me["all_workspaces"] is True
        assert {w["slug"] for w in me["workspaces"]} == {workspace.slug, second_workspace.slug}

        refreshed = Client().post(
            "/auth/mcp/token/",
            {"grant_type": "refresh_token", "client_id": client_id, "refresh_token": body["refresh_token"]},
        )
        assert refreshed.status_code == 200
        assert self.whoami(refreshed.json()["access_token"])["all_workspaces"] is True

    def projects(self, access_token, slug):
        return Client().get(f"/api/v1/workspaces/{slug}/projects/", HTTP_X_API_KEY=access_token)

    def test_the_api_keeps_a_single_workspace_connection_in_its_workspace(
        self, db, workspace, second_workspace, create_user
    ):
        browser = Client()
        browser.force_login(create_user)
        _, body = self.connect(browser, {"workspace": second_workspace.slug})
        assert self.projects(body["access_token"], second_workspace.slug).status_code == 200
        other = self.projects(body["access_token"], workspace.slug)
        assert other.status_code == 403
        assert "only has access to the workspace" in other.json()["detail"]
        # routes without a workspace still work (the MCP needs whoami to start)
        assert self.whoami(body["access_token"])["workspace_slug"] == second_workspace.slug

    def test_every_workspace_and_personal_tokens_reach_every_workspace(
        self, db, workspace, second_workspace, create_user
    ):
        browser = Client()
        browser.force_login(create_user)
        _, body = self.connect(browser, {"workspace": second_workspace.slug, "all_workspaces": "on"})
        assert self.projects(body["access_token"], workspace.slug).status_code == 200

        personal = APIToken.objects.create(user=create_user, label="mine", token="plane_api_personal_token")
        assert self.projects(personal.token, workspace.slug).status_code == 200
        assert self.projects(personal.token, second_workspace.slug).status_code == 200


@pytest.mark.contract
class TestConnectorTokensInTheList:
    @pytest.fixture(autouse=True)
    def _public_url(self, settings):
        settings.APP_BASE_URL = BASE
        settings.WEB_URL = BASE

    def test_a_connector_shows_connected_past_its_expiry_and_replaced_ones_disappear(
        self, db, workspace, create_user
    ):
        from datetime import timedelta

        from django.utils import timezone

        browser = Client()
        browser.force_login(create_user)
        flow = TestMcpOAuthAllWorkspaces()
        _, first = flow.connect(browser, {"workspace": workspace.slug})
        _, second = flow.connect(browser, {"workspace": workspace.slug})
        yesterday = timezone.now() - timedelta(days=1)
        manual = APIToken.objects.create(user=create_user, label="manual", expired_at=yesterday)
        # not used for days: the access token is past its 24h, the app renews it on its next call
        APIToken.objects.filter(token=second["access_token"]).update(expired_at=timezone.now() - timedelta(days=2))

        listed = {t["label"]: t for t in browser.get("/api/users/api-tokens/").json()}
        assert set(listed) == {"Claude (conector)", "manual"}  # the replaced connection is not listed
        assert listed["Claude (conector)"]["is_connector"] is True
        assert listed["Claude (conector)"]["is_active"] is True
        assert listed["manual"]["is_connector"] is False
        assert listed["manual"]["is_active"] is False
        assert str(manual.id) == listed["manual"]["id"]
        assert not APIToken.objects.get(token=first["access_token"]).is_active


@pytest.mark.contract
class TestProjectVisibilityThroughTheApi:
    def test_a_project_can_be_made_secret_and_public_again(self, api_key_client, workspace, project):
        url = f"/api/v1/workspaces/{workspace.slug}/projects/{project.id}/"
        secret = api_key_client.patch(url, {"network": 0}, format="json")
        assert secret.status_code == 200, secret.data
        project.refresh_from_db()
        assert project.network == 0

        assert api_key_client.patch(url, {"network": 2}, format="json").status_code == 200
        project.refresh_from_db()
        assert project.network == 2

    def test_an_unknown_visibility_is_rejected(self, api_key_client, workspace, project):
        url = f"/api/v1/workspaces/{workspace.slug}/projects/{project.id}/"
        assert api_key_client.patch(url, {"network": 7}, format="json").status_code == 400


@pytest.mark.contract
class TestMemberListsCarryTheirMembership:
    def test_workspace_and_project_members_say_role_activity_and_bot(
        self, api_key_client, workspace, project, create_user
    ):
        members = api_key_client.get(f"/api/v1/workspaces/{workspace.slug}/members/").json()
        me = next(m for m in members if m["id"] == str(create_user.id))
        assert {k: me[k] for k in ("role", "role_slug", "is_active", "is_bot")} == {
            "role": 20,
            "role_slug": "admin",
            "is_active": True,
            "is_bot": False,
        }
        in_project = api_key_client.get(f"/api/v1/workspaces/{workspace.slug}/projects/{project.id}/members/").json()
        assert [m["role_slug"] for m in in_project if m["id"] == str(create_user.id)] == ["admin"]


@pytest.mark.contract
class TestModuleUpdateAnswersWithTheWholeModule:
    def test_patch_returns_what_retrieve_returns(self, api_key_client, workspace, project):
        from plane.db.models import Module

        project.module_view = True
        project.save(update_fields=["module_view"])
        module = Module.objects.create(name="Lanzamiento", project=project, workspace=workspace)
        url = f"/api/v1/workspaces/{workspace.slug}/projects/{project.id}/modules/{module.id}/"
        patched = api_key_client.patch(url, {"status": "in-progress"}, format="json")
        assert patched.status_code == 200, patched.json()
        body = patched.json()
        assert body["status"] == "in-progress"
        assert body["name"] == "Lanzamiento"
        assert set(api_key_client.get(url).json()) <= set(body)
