# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import threading
from unittest import mock

import pytest
from django.db import connection
from rest_framework import status
from rest_framework.test import APIClient

from plane.authentication.utils.zil_provisioning import get_service_user
from plane.db.models import Page, PageZilClientLink, ZilClientsRoot
from plane.utils import zil_client_folders
from plane.utils.zil_client_folders import apply_client_folders

NIKE = "0123456789abcdef01234567"
ADIDAS = "0123456789abcdef01234568"
ZIL_ENV = {"ZIL_BASE_URL": "http://zil.test", "ZIL_SERVICE_SECRET": "secret"}


@pytest.fixture(autouse=True)
def no_background_tasks():
    with (
        mock.patch("plane.app.views.page.base.page_transaction.delay"),
        mock.patch("plane.app.views.page.base.recent_visited_task.delay"),
        mock.patch("plane.app.views.page.base.refresh_zil_client_link.delay"),
        mock.patch.dict("os.environ", ZIL_ENV),
    ):
        yield


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
    # Zil calls with the service key and no session: never reuse a client a test logged in
    service_client = APIClient()
    service_client.credentials(HTTP_X_ZIL_SERVICE_KEY="secret")
    return service_client.post(
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


def clients_root(project):
    return ZilClientsRoot.objects.select_related("page").get(project_id=project["id"])


@pytest.mark.contract
class TestClientsFolder:
    @pytest.mark.django_db
    def test_first_roster_creates_the_clients_folder_with_nobody_setting_it_up(self, api_client, workspace, project):
        response = push(api_client, workspace, [client_dto(NIKE, "Nike")])
        assert response.status_code == status.HTTP_200_OK
        assert response.data["roots"] == 1 and response.data["created"] == 1

        root = clients_root(project).page
        assert root.name == "Clientes" and root.kind == Page.FOLDER_KIND and root.parent_id is None
        assert root.access == Page.PUBLIC_ACCESS
        assert folder_of(NIKE).parent_id == root.id

    @pytest.mark.django_db
    def test_adopts_an_existing_clientes_folder(self, session_client, api_client, workspace, project):
        existing = create_folder(session_client, workspace, project)
        push(api_client, workspace, [client_dto(NIKE, "Nike")])
        assert str(clients_root(project).page_id) == str(existing["id"])
        assert Page.objects.filter(name="Clientes", kind=Page.FOLDER_KIND).count() == 1

    @pytest.mark.django_db
    def test_folders_made_under_an_adopted_clientes_folder_belong_to_the_service_user(
        self, session_client, api_client, workspace, project, create_user
    ):
        # someone made "Clientes" by hand: it is adopted, but the folders the sync makes in it are not theirs
        existing = create_folder(session_client, workspace, project)
        push(api_client, workspace, [client_dto(NIKE, "Nike")])

        service = get_service_user()
        nike = folder_of(NIKE)
        assert str(nike.parent_id) == str(existing["id"])
        assert nike.owned_by_id == service.id and nike.created_by_id == service.id
        assert PageZilClientLink.objects.get(zil_client_id=NIKE).created_by_id == service.id
        # the folder that was theirs stays theirs
        assert Page.objects.get(pk=existing["id"]).owned_by_id == create_user.id

    @pytest.mark.django_db
    def test_no_clients_no_folder(self, api_client, workspace, project):
        response = push(api_client, workspace, [])
        assert response.data["roots"] == 0
        assert not ZilClientsRoot.objects.exists()

    @pytest.mark.django_db
    def test_an_archived_clients_folder_is_replaced_and_keeps_its_clients(self, api_client, workspace, project):
        push(api_client, workspace, [client_dto(NIKE, "Nike")])
        old_root = clients_root(project).page
        Page.objects.filter(pk__in=[old_root.pk, folder_of(NIKE).pk]).update(archived_at="2026-10-01")

        push(api_client, workspace, [client_dto(NIKE, "Nike")])
        new_root = clients_root(project).page
        assert new_root.pk != old_root.pk and new_root.archived_at is None
        nike = folder_of(NIKE)
        assert nike.parent_id == new_root.pk and nike.archived_at is None


@pytest.mark.contract
class TestClientFoldersSync:
    @pytest.mark.django_db
    def test_requires_service_key(self, api_client, workspace):
        response = api_client.post(
            "/api/zil/sync/client-folders/", {"workspace_slug": workspace.slug, "clients": []}, format="json"
        )
        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)

    @pytest.mark.django_db
    def test_creates_one_linked_folder_per_client_idempotently(self, api_client, workspace, project):
        response = push(api_client, workspace, [client_dto(NIKE, "Nike"), client_dto(ADIDAS, "Adidas")])
        assert response.status_code == status.HTTP_200_OK
        assert response.data["created"] == 2

        nike = folder_of(NIKE)
        assert nike.name == "Nike" and nike.parent_id == clients_root(project).page_id
        assert nike.kind == Page.FOLDER_KIND and nike.access == Page.PUBLIC_ACCESS

        again = push(api_client, workspace, [client_dto(NIKE, "Nike"), client_dto(ADIDAS, "Adidas")])
        assert again.data["created"] == 0
        assert PageZilClientLink.objects.count() == 2
        assert ZilClientsRoot.objects.count() == 1

    @pytest.mark.django_db
    def test_renames_unless_renamed_by_hand(self, api_client, workspace, project):
        push(api_client, workspace, [client_dto(NIKE, "Nike"), client_dto(ADIDAS, "Adidas")])
        Page.objects.filter(pk=folder_of(ADIDAS).pk).update(name="Adidas (cuenta LATAM)")

        response = push(api_client, workspace, [client_dto(NIKE, "Nike Inc"), client_dto(ADIDAS, "Adidas Group")])
        assert response.data["renamed"] == 1
        assert folder_of(NIKE).name == "Nike Inc"
        assert folder_of(ADIDAS).name == "Adidas (cuenta LATAM)"

    @pytest.mark.django_db
    def test_archives_only_on_authoritative_roster_and_restores(self, api_client, workspace, project):
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
    def test_respects_a_folder_linked_by_hand(self, session_client, api_client, workspace, project):
        manual = create_folder(session_client, workspace, project, name="Nike a mano")
        with mock.patch("plane.app.views.page.zil_client.get_zil_client", return_value=client_dto(NIKE, "Nike")):
            linked = session_client.post(
                pages_url(workspace, project, f"{manual['id']}/zil-client/"), {"zil_client_id": NIKE}, format="json"
            )
        assert linked.status_code == status.HTTP_200_OK

        response = push(api_client, workspace, [client_dto(NIKE, "Nike"), client_dto(ADIDAS, "Adidas")])
        assert response.data["created"] == 1
        push(api_client, workspace, [client_dto(ADIDAS, "Adidas")])
        # a hand-linked folder is never archived by the sync
        assert str(folder_of(NIKE).pk) == str(manual["id"]) and folder_of(NIKE).archived_at is None


@pytest.mark.contract
class TestClientProfileRelay:
    @pytest.mark.django_db
    def test_profile_is_relayed_as_the_user_and_refreshes_the_cache(
        self, session_client, api_client, workspace, project, create_user
    ):
        push(api_client, workspace, [client_dto(NIKE, "Nike")])
        folder = folder_of(NIKE)
        info = {
            "alias": "Nike Inc",
            "companyName": "Nike SA",
            "lifecycleStatus": "paused",
            "businessUnit": {"slug": "mw"},
        }
        with mock.patch(
            "plane.app.views.page.zil_client.zil_client_relay",
            return_value=(200, {"profile": {"id": NIKE, "info": info}}),
        ) as relay:
            response = session_client.get(pages_url(workspace, project, f"{folder.id}/zil-client/profile/"))
        assert response.status_code == status.HTTP_200_OK
        assert response.data["info"]["alias"] == "Nike Inc"
        relay.assert_called_once_with("GET", NIKE, "/profile", workspace.slug, create_user.email, json=None, files=None)
        assert PageZilClientLink.objects.get(zil_client_id=NIKE).lifecycle_status == "paused"

    @pytest.mark.django_db
    def test_zil_refusal_passes_through(self, session_client, api_client, workspace, project):
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
    def test_brand_file_redirects_to_the_signed_url(self, session_client, api_client, workspace, project):
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


@pytest.mark.contract
class TestClientsFolderLifecycle:
    @pytest.mark.django_db
    def test_a_deleted_clients_folder_is_replaced_and_its_clients_come_back_under_the_new_one(
        self, session_client, api_client, workspace, project
    ):
        push(api_client, workspace, [client_dto(NIKE, "Nike"), client_dto(ADIDAS, "Adidas")])
        old_root = clients_root(project).page
        # what a person does: archive the Clientes folder, then delete it (its children move up a level)
        archived = session_client.post(pages_url(workspace, project, f"{old_root.id}/archive/"))
        assert archived.status_code == status.HTTP_200_OK
        deleted = session_client.delete(pages_url(workspace, project, f"{old_root.id}/"))
        assert deleted.status_code == status.HTTP_204_NO_CONTENT

        push(api_client, workspace, [client_dto(NIKE, "Nike"), client_dto(ADIDAS, "Adidas")])
        new_root = clients_root(project).page
        assert new_root.pk != old_root.pk
        for client_id in (NIKE, ADIDAS):
            folder = folder_of(client_id)
            assert folder.archived_at is None
            assert folder.parent_id == new_root.pk

    @pytest.mark.django_db
    def test_a_clients_folder_in_an_archived_project_is_replaced_in_a_live_one(
        self, session_client, api_client, workspace, project
    ):
        push(api_client, workspace, [client_dto(NIKE, "Nike")])
        archived = session_client.post(f"/api/workspaces/{workspace.slug}/projects/{project['id']}/archive/")
        assert archived.status_code == status.HTTP_200_OK
        other = session_client.post(
            f"/api/workspaces/{workspace.slug}/projects/", {"name": "Second", "identifier": "SEC"}, format="json"
        )
        assert other.status_code == status.HTTP_201_CREATED

        push(api_client, workspace, [client_dto(NIKE, "Nike")])
        live = ZilClientsRoot.objects.get(project_id=other.data["id"])
        assert PageZilClientLink.objects.get(project_id=other.data["id"], zil_client_id=NIKE).page.parent_id == (
            live.page_id
        )

    @pytest.mark.django_db
    def test_a_folder_someone_moved_into_another_folder_keeps_its_place_through_archive_and_restore(
        self, session_client, api_client, workspace, project
    ):
        push(api_client, workspace, [client_dto(NIKE, "Nike"), client_dto(ADIDAS, "Adidas")])
        group = create_folder(session_client, workspace, project, name="Grupo")
        moved = session_client.post(
            pages_url(workspace, project, f"{folder_of(NIKE).id}/move-in-tree/"),
            {"parent_id": group["id"]},
            format="json",
        )
        assert moved.status_code == status.HTTP_200_OK

        push(api_client, workspace, [client_dto(ADIDAS, "Adidas")])
        assert folder_of(NIKE).archived_at is not None
        push(api_client, workspace, [client_dto(NIKE, "Nike"), client_dto(ADIDAS, "Adidas")])
        nike = folder_of(NIKE)
        assert nike.archived_at is None and str(nike.parent_id) == str(group["id"])

    @pytest.mark.django_db
    def test_long_and_empty_names_fit_and_do_not_rename_on_the_next_push(self, api_client, workspace, project):
        roster = [
            {"id": NIKE, "alias": "N" * 400, "companyName": "x", "lifecycleStatus": "active", "businessUnitSlug": "mw"},
            {"id": ADIDAS, "alias": "", "companyName": "", "lifecycleStatus": "active", "businessUnitSlug": ""},
        ]
        assert push(api_client, workspace, roster).status_code == status.HTTP_200_OK
        assert folder_of(NIKE).name == "N" * 255
        assert folder_of(ADIDAS).name == "Cliente"
        assert push(api_client, workspace, roster).data["renamed"] == 0

    @pytest.mark.django_db
    def test_the_clients_folder_itself_cannot_be_linked_to_a_client(
        self, session_client, api_client, workspace, project
    ):
        push(api_client, workspace, [client_dto(NIKE, "Nike")])
        root = clients_root(project).page
        with mock.patch("plane.app.views.page.zil_client.get_zil_client", return_value=client_dto(ADIDAS, "Adidas")):
            response = session_client.post(
                pages_url(workspace, project, f"{root.id}/zil-client/"), {"zil_client_id": ADIDAS}, format="json"
            )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["error_message"] == "PAGE_IS_CLIENTS_ROOT"
        # and the client keeps getting its own folder
        push(api_client, workspace, [client_dto(NIKE, "Nike"), client_dto(ADIDAS, "Adidas")])
        assert folder_of(ADIDAS).parent_id == root.id

    @pytest.mark.django_db
    def test_a_sync_keeps_who_linked_a_folder_by_hand(
        self, session_client, api_client, workspace, project, create_user
    ):
        manual = create_folder(session_client, workspace, project, name="Nike a mano")
        with mock.patch("plane.app.views.page.zil_client.get_zil_client", return_value=client_dto(NIKE, "Nike")):
            session_client.post(
                pages_url(workspace, project, f"{manual['id']}/zil-client/"), {"zil_client_id": NIKE}, format="json"
            )
        assert PageZilClientLink.objects.get(zil_client_id=NIKE).created_by_id == create_user.id

        push(api_client, workspace, [client_dto(NIKE, "Nike"), client_dto(ADIDAS, "Adidas")])
        assert PageZilClientLink.objects.get(zil_client_id=NIKE).created_by_id == create_user.id
        # what the sync creates carries the service user that owns it, not "nobody"
        created = folder_of(ADIDAS)
        assert created.created_by_id == created.owned_by_id
        assert PageZilClientLink.objects.get(zil_client_id=ADIDAS).created_by_id == created.owned_by_id


@pytest.mark.contract
class TestConcurrentPushes:
    @pytest.mark.django_db(transaction=True)
    def test_two_pushes_at_once_leave_one_clients_folder_and_one_folder_per_client(self, workspace, project):
        get_service_user()
        clients = [client_dto(NIKE, "Nike"), client_dto(ADIDAS, "Adidas")]
        # both pushes get past "there is no clients folder yet" before either one creates it
        meeting = threading.Barrier(2)
        real_main_project = zil_client_folders._main_project

        def main_project_after_meeting(workspace_):
            try:
                meeting.wait(timeout=2)
            except threading.BrokenBarrierError:
                pass  # the other push is queued behind this one: nothing to wait for
            return real_main_project(workspace_)

        outcomes = []

        def push_roster():
            try:
                outcomes.append(apply_client_folders(workspace.id, clients, True))
            except Exception as error:  # noqa: BLE001 - the test reports whatever the push raised
                outcomes.append(error)
            finally:
                connection.close()

        with mock.patch.object(zil_client_folders, "_main_project", main_project_after_meeting):
            threads = [threading.Thread(target=push_roster) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

        assert [o for o in outcomes if isinstance(o, Exception)] == []
        assert ZilClientsRoot.objects.count() == 1
        assert Page.objects.filter(name="Clientes", kind=Page.FOLDER_KIND).count() == 1
        assert PageZilClientLink.objects.count() == 2
