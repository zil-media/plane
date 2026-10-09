# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import base64
from unittest import mock

import pytest
import requests
from rest_framework import status

from plane.db.models import APIToken, Page, Project, ProjectMember, ProjectPage, User, WorkspaceMember

LIVE_SETTINGS = {"LIVE_URL": "http://live.test/live/", "LIVE_SERVER_SECRET_KEY": "live-secret"}


@pytest.fixture
def project(db, workspace, create_user):
    project = Project.objects.create(name="Docs", identifier="DOC", workspace=workspace, created_by=create_user)
    ProjectMember.objects.create(project=project, member=create_user, role=20, is_active=True)
    return project


@pytest.fixture
def other_user(db, workspace):
    user = User.objects.create(email="other@plane.so", username="other_user")
    WorkspaceMember.objects.create(workspace=workspace, member=user, role=15)
    return user


@pytest.fixture
def other_client(api_client, other_user):
    token = APIToken.objects.create(user=other_user, label="other", token="other-api-token-12345")
    api_client.credentials(HTTP_X_API_KEY=token.token)
    return api_client


def make_page(project, owner, name="Runbook", html="<p>Hola</p>", access=Page.PUBLIC_ACCESS, binary=None):
    page = Page.objects.create(
        workspace=project.workspace,
        name=name,
        description_html=html,
        description_binary=binary,
        owned_by=owner,
        access=access,
    )
    ProjectPage.objects.create(workspace=project.workspace, project=project, page=page)
    return page


def pages_url(workspace, project, page=None):
    base = f"/api/v1/workspaces/{workspace.slug}/projects/{project.id}/pages/"
    return f"{base}{page.id}/" if page else base


def live_response(html, binary=b"new-yjs-state", live=False):
    response = mock.Mock(status_code=200)
    response.json.return_value = {
        "applied_to_live_document": live,
        "description_binary": base64.b64encode(binary).decode(),
        "description_html": html,
        "description_json": {"type": "doc"},
    }
    return response


@pytest.mark.contract
class TestPageListCreate:
    @pytest.mark.django_db
    def test_create_page(self, api_key_client, workspace, project, create_user):
        response = api_key_client.post(
            pages_url(workspace, project),
            {"name": "Onboarding", "description_html": "<h2>Contexto</h2><p>Texto</p>"},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        page = Page.objects.get(pk=response.data["id"])
        assert page.name == "Onboarding"
        assert page.owned_by == create_user
        assert page.description_html == "<h2>Contexto</h2><p>Texto</p>"
        # the editor builds the collaborative document from the HTML on first open
        assert page.description_binary is None
        assert ProjectPage.objects.filter(page=page, project=project).exists()
        assert response.data["description_html"] == page.description_html

    @pytest.mark.django_db
    def test_create_page_strips_scripts(self, api_key_client, workspace, project):
        response = api_key_client.post(
            pages_url(workspace, project),
            {"name": "XSS", "description_html": "<p>ok</p><script>alert(1)</script>"},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert "<script" not in Page.objects.get(pk=response.data["id"]).description_html

    @pytest.mark.django_db
    def test_list_hides_others_private_and_archived_pages(
        self, api_key_client, workspace, project, create_user, other_user
    ):
        ProjectMember.objects.create(project=project, member=other_user, role=15, is_active=True)
        visible = make_page(project, create_user, name="Mine")
        make_page(project, other_user, name="Theirs public")
        make_page(project, other_user, name="Theirs private", access=Page.PRIVATE_ACCESS)
        archived = make_page(project, create_user, name="Old")
        archived.archived_at = "2026-01-01"
        archived.save()

        response = api_key_client.get(pages_url(workspace, project))

        assert response.status_code == status.HTTP_200_OK
        names = {page["name"] for page in response.data["results"]}
        assert names == {"Mine", "Theirs public"}
        assert "description_html" not in response.data["results"][0]

        response = api_key_client.get(pages_url(workspace, project), {"search": "min"})
        assert [str(page["id"]) for page in response.data["results"]] == [str(visible.id)]

    @pytest.mark.django_db
    def test_non_member_cannot_list_or_create(self, other_client, workspace, project):
        assert other_client.get(pages_url(workspace, project)).status_code == status.HTTP_403_FORBIDDEN
        response = other_client.post(pages_url(workspace, project), {"name": "Nope"}, format="json")
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert not Page.objects.filter(name="Nope").exists()


@pytest.mark.contract
class TestPageDetail:
    @pytest.mark.django_db
    def test_get_page_with_body(self, api_key_client, workspace, project, create_user):
        page = make_page(project, create_user)

        response = api_key_client.get(pages_url(workspace, project, page))

        assert response.status_code == status.HTTP_200_OK
        assert response.data["name"] == "Runbook"
        assert response.data["description_html"] == "<p>Hola</p>"

    @pytest.mark.django_db
    def test_non_member_cannot_read_or_update(self, other_client, workspace, project, create_user):
        page = make_page(project, create_user)

        assert other_client.get(pages_url(workspace, project, page)).status_code == status.HTTP_403_FORBIDDEN
        response = other_client.patch(pages_url(workspace, project, page), {"name": "Hacked"}, format="json")
        assert response.status_code == status.HTTP_403_FORBIDDEN
        page.refresh_from_db()
        assert page.name == "Runbook"

    @pytest.mark.django_db
    def test_member_cannot_touch_someone_elses_private_page(
        self, other_client, workspace, project, create_user, other_user
    ):
        ProjectMember.objects.create(project=project, member=other_user, role=15, is_active=True)
        page = make_page(project, create_user, access=Page.PRIVATE_ACCESS)

        assert other_client.get(pages_url(workspace, project, page)).status_code == status.HTTP_403_FORBIDDEN
        response = other_client.patch(
            pages_url(workspace, project, page), {"description_html": "<p>x</p>"}, format="json"
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.django_db
    def test_update_body_goes_through_live_server(self, api_key_client, workspace, project, create_user, settings):
        for key, value in LIVE_SETTINGS.items():
            setattr(settings, key, value)
        page = make_page(project, create_user, binary=b"stored-yjs-state")

        with mock.patch(
            "plane.utils.page_content.requests.post",
            return_value=live_response("<p>Hola</p><p>Nuevo párrafo</p>", live=True),
        ) as post:
            response = api_key_client.patch(
                pages_url(workspace, project, page),
                {"description_html": "<p>Hola</p><p>Nuevo párrafo</p>"},
                format="json",
            )

        assert response.status_code == status.HTTP_200_OK
        # the live server gets the new body plus the stored document to merge onto
        url = post.call_args.args[0]
        sent = post.call_args.kwargs
        assert url == f"http://live.test/live/page-content/{page.id}/apply/"
        assert sent["headers"] == {"live-server-secret-key": "live-secret"}
        assert sent["json"]["description_html"] == "<p>Hola</p><p>Nuevo párrafo</p>"
        assert "name" not in sent["json"]
        assert base64.b64decode(sent["json"]["current_description_binary"]) == b"stored-yjs-state"

        page.refresh_from_db()
        assert bytes(page.description_binary) == b"new-yjs-state"
        assert page.description_html == "<p>Hola</p><p>Nuevo párrafo</p>"
        assert page.description_stripped == "HolaNuevo párrafo"
        assert response.data["description_html"] == page.description_html

    @pytest.mark.django_db
    def test_rename_updates_document_title(self, api_key_client, workspace, project, create_user, settings):
        for key, value in LIVE_SETTINGS.items():
            setattr(settings, key, value)
        page = make_page(project, create_user)

        with mock.patch("plane.utils.page_content.requests.post", return_value=live_response("<p>Hola</p>")) as post:
            response = api_key_client.patch(pages_url(workspace, project, page), {"name": "Runbook v2"}, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert post.call_args.kwargs["json"]["name"] == "Runbook v2"
        assert "description_html" not in post.call_args.kwargs["json"]
        page.refresh_from_db()
        assert page.name == "Runbook v2"

    @pytest.mark.django_db
    def test_live_server_down_changes_nothing(self, api_key_client, workspace, project, create_user, settings):
        for key, value in LIVE_SETTINGS.items():
            setattr(settings, key, value)
        page = make_page(project, create_user)

        with mock.patch("plane.utils.page_content.requests.post", side_effect=requests.ConnectionError("down")):
            response = api_key_client.patch(
                pages_url(workspace, project, page), {"name": "New", "description_html": "<p>x</p>"}, format="json"
            )

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        page.refresh_from_db()
        assert page.name == "Runbook"
        assert page.description_html == "<p>Hola</p>"

    @pytest.mark.django_db
    def test_locked_and_archived_pages_reject_edits(self, api_key_client, workspace, project, create_user):
        page = make_page(project, create_user)
        lock_url = pages_url(workspace, project, page) + "lock/"
        assert api_key_client.post(lock_url).status_code == status.HTTP_204_NO_CONTENT

        response = api_key_client.patch(pages_url(workspace, project, page), {"name": "x"}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["error"] == "Page is locked"

        assert api_key_client.delete(lock_url).status_code == status.HTTP_204_NO_CONTENT
        archive_url = pages_url(workspace, project, page) + "archive/"
        assert api_key_client.post(archive_url).status_code == status.HTTP_200_OK
        response = api_key_client.patch(pages_url(workspace, project, page), {"name": "x"}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["error"] == "Page is archived"

        assert api_key_client.delete(archive_url).status_code == status.HTTP_200_OK
        page.refresh_from_db()
        assert page.archived_at is None
