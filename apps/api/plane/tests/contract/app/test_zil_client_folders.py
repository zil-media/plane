# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from unittest import mock

import pytest
from rest_framework import status

from plane.db.models import Page, PageZilClientLink, ZilClientsRoot

NIKE = "0123456789abcdef01234567"
ADIDAS = "0123456789abcdef01234568"
ZIL_ENV = {"ZIL_BASE_URL": "http://zil.test", "ZIL_SERVICE_SECRET": "secret"}


@pytest.fixture(autouse=True)
def no_background_tasks():
    with (
        mock.patch("plane.app.views.page.base.page_transaction.delay"),
        mock.patch("plane.app.views.page.base.recent_visited_task.delay"),
        mock.patch("plane.app.views.page.base.refresh_zil_client_link.delay"),
        mock.patch("plane.app.views.page.zil_client.sync_zil_client_folders", return_value=None) as sync,
        mock.patch.dict("os.environ", ZIL_ENV),
    ):
        yield sync


@pytest.fixture
def project(session_client, workspace):
    response = session_client.post(
        f"/api/workspaces/{workspace.slug}/projects/",
        {"name": "Clients Project", "identifier": "CLP"},
        format="json",
    )
    assert response.status_code == status.HTTP_201_CREATED
    return response.data


def pages_url(workspace, project, suffix=""):
    return f"/api/workspaces/{workspace.slug}/projects/{project['id']}/pages/{suffix}"


def create_folder(client, workspace, project, **data):
    response = client.post(pages_url(workspace, project), {"name": "Clientes", "kind": "folder", **data}, format="json")
    assert response.status_code == status.HTTP_201_CREATED, response.data
    return response.data


def push(api_client, workspace, clients, authoritative=True):
    api_client.credentials(HTTP_X_ZIL_SERVICE_KEY="secret")
    return api_client.post(
        "/api/zil/sync/client-folders/",
        {"workspace_slug": workspace.slug, "clients": clients, "authoritative": authoritative},
        format="json",
    )


def client_dto(client_id, alias, status_="active"):
    return {
        "id": client_id,
        "alias": alias,
        "companyName": f"{alias} SA",
        "lifecycleStatus": status_,
        "businessUnitSlug": "mw",
    }


def folder_of(client_id):
    return PageZilClientLink.objects.select_related("page").get(zil_client_id=client_id).page


@pytest.fixture
def root(session_client, workspace, project, no_background_tasks):
    folder = create_folder(session_client, workspace, project)
    response = session_client.post(pages_url(workspace, project, f"{folder['id']}/zil-clients-root/"))
    assert response.status_code == status.HTTP_200_OK, response.data
    no_background_tasks.assert_called_once_with(workspace.slug)
    return folder


@pytest.mark.contract
class TestClientsRoot:
    @pytest.mark.django_db
    def test_root_is_flagged_and_one_per_project(self, session_client, workspace, project, root):
        detail = session_client.get(pages_url(workspace, project, f"{root['id']}/"))
        assert detail.data["is_zil_clients_root"] is True

        other = create_folder(session_client, workspace, project, name="Otra")
        response = session_client.post(pages_url(workspace, project, f"{other['id']}/zil-clients-root/"))
        assert response.status_code == status.HTTP_200_OK
        assert ZilClientsRoot.objects.filter(project_id=project["id"]).count() == 1
        assert ZilClientsRoot.objects.get(project_id=project["id"]).page_id == other["id"]

    @pytest.mark.django_db
    def test_private_folder_cannot_be_root(self, session_client, workspace, project):
        folder = create_folder(session_client, workspace, project, access=1)
        response = session_client.post(pages_url(workspace, project, f"{folder['id']}/zil-clients-root/"))
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["error_message"] == "ZIL_ROOT_NOT_PUBLIC"


@pytest.mark.contract
class TestClientFoldersSync:
    @pytest.mark.django_db
    def test_requires_service_key(self, api_client, workspace):
        response = api_client.post(
            "/api/zil/sync/client-folders/", {"workspace_slug": workspace.slug, "clients": []}, format="json"
        )
        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)

    @pytest.mark.django_db
    def test_creates_one_linked_folder_per_client_idempotently(self, api_client, workspace, root):
        response = push(api_client, workspace, [client_dto(NIKE, "Nike"), client_dto(ADIDAS, "Adidas")])
        assert response.status_code == status.HTTP_200_OK
        assert response.data["created"] == 2

        nike = folder_of(NIKE)
        assert nike.name == "Nike" and nike.parent_id == root["id"] and nike.kind == Page.FOLDER_KIND
        assert nike.access == Page.PUBLIC_ACCESS

        again = push(api_client, workspace, [client_dto(NIKE, "Nike"), client_dto(ADIDAS, "Adidas")])
        assert again.data["created"] == 0
        assert PageZilClientLink.objects.count() == 2

    @pytest.mark.django_db
    def test_renames_unless_renamed_by_hand(self, api_client, workspace, root):
        push(api_client, workspace, [client_dto(NIKE, "Nike"), client_dto(ADIDAS, "Adidas")])
        Page.objects.filter(pk=folder_of(ADIDAS).pk).update(name="Adidas (cuenta LATAM)")

        response = push(api_client, workspace, [client_dto(NIKE, "Nike Inc"), client_dto(ADIDAS, "Adidas Group")])
        assert response.data["renamed"] == 1
        assert folder_of(NIKE).name == "Nike Inc"
        assert folder_of(ADIDAS).name == "Adidas (cuenta LATAM)"

    @pytest.mark.django_db
    def test_archives_only_on_authoritative_roster_and_restores(self, api_client, workspace, root):
        push(api_client, workspace, [client_dto(NIKE, "Nike"), client_dto(ADIDAS, "Adidas")])

        push(api_client, workspace, [client_dto(NIKE, "Nike")], authoritative=False)
        assert folder_of(ADIDAS).archived_at is None

        response = push(api_client, workspace, [client_dto(NIKE, "Nike")])
        assert response.data["archived"] == 1
        assert folder_of(ADIDAS).archived_at is not None

        response = push(api_client, workspace, [client_dto(NIKE, "Nike"), client_dto(ADIDAS, "Adidas")])
        assert response.data["restored"] == 1
        assert folder_of(ADIDAS).archived_at is None

    @pytest.mark.django_db
    def test_respects_a_folder_linked_by_hand(self, session_client, api_client, workspace, project, root):
        manual = create_folder(session_client, workspace, project, name="Nike a mano")
        with mock.patch("plane.app.views.page.zil_client.get_zil_client", return_value=client_dto(NIKE, "Nike")):
            linked = session_client.post(
                pages_url(workspace, project, f"{manual['id']}/zil-client/"), {"zil_client_id": NIKE}, format="json"
            )
        assert linked.status_code == status.HTTP_200_OK

        response = push(api_client, workspace, [client_dto(ADIDAS, "Adidas")])
        assert response.data["created"] == 1
        # a hand-linked folder is never archived by the sync
        assert folder_of(NIKE).pk == manual["id"] and folder_of(NIKE).archived_at is None


@pytest.mark.contract
class TestClientProfileRelay:
    @pytest.mark.django_db
    def test_profile_is_relayed_as_the_user_and_refreshes_the_cache(
        self, session_client, api_client, workspace, project, root, create_user
    ):
        push(api_client, workspace, [client_dto(NIKE, "Nike")])
        folder = folder_of(NIKE)
        profile = {
            "id": NIKE,
            "info": {
                "alias": "Nike Inc",
                "companyName": "Nike SA",
                "lifecycleStatus": "paused",
                "businessUnit": {"slug": "mw"},
            },
        }
        with mock.patch(
            "plane.app.views.page.zil_client.zil_client_relay", return_value=(200, {"profile": profile})
        ) as relay:
            response = session_client.get(pages_url(workspace, project, f"{folder.id}/zil-client/profile/"))
        assert response.status_code == status.HTTP_200_OK
        assert response.data["info"]["alias"] == "Nike Inc"
        relay.assert_called_once_with("GET", NIKE, "/profile", workspace.slug, create_user.email, json=None, files=None)
        assert PageZilClientLink.objects.get(zil_client_id=NIKE).lifecycle_status == "paused"

    @pytest.mark.django_db
    def test_zil_refusal_passes_through(self, session_client, api_client, workspace, project, root):
        push(api_client, workspace, [client_dto(NIKE, "Nike")])
        folder = folder_of(NIKE)
        with mock.patch(
            "plane.app.views.page.zil_client.zil_client_relay",
            return_value=(403, {"message": "actor not in workspace"}),
        ):
            response = session_client.post(
                pages_url(workspace, project, f"{folder.id}/zil-client/assets/"),
                {"kind": "link", "label": "Sitio"},
                format="json",
            )
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.data["error"] == "actor not in workspace"

    @pytest.mark.django_db
    def test_brand_file_redirects_to_the_signed_url(self, session_client, api_client, workspace, project, root):
        push(api_client, workspace, [client_dto(NIKE, "Nike")])
        folder = folder_of(NIKE)
        signed = "https://r2.test/client-brand/logo.png?sig=1"
        with mock.patch("plane.app.views.page.zil_client.zil_client_relay", return_value=(200, {"url": signed})):
            response = session_client.get(
                pages_url(workspace, project, f"{folder.id}/zil-client/brand-files/{ADIDAS}/")
            )
        assert response.status_code == status.HTTP_302_FOUND
        assert response["Location"] == signed

    @pytest.mark.django_db
    def test_unlinked_folder_has_no_profile(self, session_client, workspace, project):
        folder = create_folder(session_client, workspace, project, name="Suelta")
        response = session_client.get(pages_url(workspace, project, f"{folder['id']}/zil-client/profile/"))
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["error_message"] == "ZIL_CLIENT_NOT_LINKED"
