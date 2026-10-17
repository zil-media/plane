# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""The folders the clients-folder sync makes are Ops's: what the next roster would undo or duplicate
on them is refused, and a folder linked by hand keeps every action."""

from unittest import mock

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework import status

from plane.db.models import Page, PageZilClientLink
from plane.tests.contract.app import test_zil_client_folders as client_folders
from plane.tests.contract.app.test_zil_client_folders import (
    ADIDAS,
    NIKE,
    client_dto,
    create_folder,
    folder_of,
    link_by_hand,
    move_in_tree,
    pages_url,
    push,
)
from plane.utils.zil_client import ZilUnavailable

# the clients-folder tests' fixtures: Zil switched on without background tasks, and a project
no_background_tasks = client_folders.no_background_tasks
project = client_folders.project

ZIL_LOOKUP = "plane.app.views.page.base.get_zil_client"


def zil_says(client):
    """Zil's answer to "is this client on the workspace's roster": a client DTO, None (gone) or an exception."""
    if isinstance(client, Exception):
        return mock.patch(ZIL_LOOKUP, side_effect=client)
    return mock.patch(ZIL_LOOKUP, return_value=client)


def archive(client, workspace, project, page):
    return client.post(pages_url(workspace, project, f"{page.id}/archive/"))


def restore(client, workspace, project, page):
    return client.delete(pages_url(workspace, project, f"{page.id}/archive/"))


def delete(client, workspace, project, page):
    return client.delete(pages_url(workspace, project, f"{page.id}/"))


def live_folders_named(name):
    return Page.objects.filter(name=name, kind=Page.FOLDER_KIND, archived_at__isnull=True).count()


@pytest.mark.contract
class TestAutoCreatedIsExposed:
    @pytest.mark.django_db
    def test_the_page_says_whether_the_sync_made_its_folder(self, session_client, workspace, project):
        push(None, workspace, [client_dto(NIKE, "Nike")])
        manual = Page.objects.get(pk=create_folder(session_client, workspace, project, name="Adidas a mano")["id"])
        link_by_hand(session_client, workspace, project, manual, ADIDAS, "Adidas")

        nike = session_client.get(pages_url(workspace, project, f"{folder_of(NIKE).id}/"))
        assert nike.data["zil_client"]["auto_created"] is True
        listed = {str(page["id"]): page for page in session_client.get(pages_url(workspace, project)).data}
        assert listed[str(manual.id)]["zil_client"]["auto_created"] is False
        assert listed[str(folder_of(NIKE).id)]["zil_client"]["auto_created"] is True


@pytest.mark.contract
class TestAutoFolderLink:
    @pytest.mark.django_db
    def test_unlinking_is_refused_and_the_next_roster_finds_its_one_folder(self, session_client, workspace, project):
        push(None, workspace, [client_dto(NIKE, "Nike")])
        nike = folder_of(NIKE)

        response = session_client.delete(pages_url(workspace, project, f"{nike.id}/zil-client/"))
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["error_message"] == "ZIL_CLIENT_FOLDER_AUTO"

        push(None, workspace, [client_dto(NIKE, "Nike")])
        assert folder_of(NIKE).pk == nike.pk
        assert live_folders_named("Nike") == 1

    @pytest.mark.django_db
    def test_linking_it_to_another_client_is_refused(self, session_client, workspace, project):
        push(None, workspace, [client_dto(NIKE, "Nike")])
        nike = folder_of(NIKE)

        with mock.patch("plane.app.views.page.zil_client.get_zil_client", return_value=client_dto(ADIDAS, "Adidas")):
            response = session_client.post(
                pages_url(workspace, project, f"{nike.id}/zil-client/"), {"zil_client_id": ADIDAS}, format="json"
            )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["error_message"] == "ZIL_CLIENT_FOLDER_AUTO"
        link = PageZilClientLink.objects.get(page_id=nike.pk)
        assert link.zil_client_id == NIKE and link.auto_created

        push(None, workspace, [client_dto(NIKE, "Nike")])
        assert live_folders_named("Nike") == 1

    @pytest.mark.django_db
    def test_a_folder_linked_by_hand_can_still_be_unlinked_and_relinked(self, session_client, workspace, project):
        manual = Page.objects.get(pk=create_folder(session_client, workspace, project, name="A mano")["id"])
        link_by_hand(session_client, workspace, project, manual, NIKE, "Nike")
        link_by_hand(session_client, workspace, project, manual, ADIDAS, "Adidas")
        assert PageZilClientLink.objects.get(page_id=manual.pk).zil_client_id == ADIDAS

        response = session_client.delete(pages_url(workspace, project, f"{manual.id}/zil-client/"))
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not PageZilClientLink.objects.filter(page_id=manual.pk).exists()


@pytest.mark.contract
class TestAutoFolderArchive:
    @pytest.mark.django_db
    def test_archiving_the_folder_of_an_active_client_is_refused(self, session_client, workspace, project):
        push(None, workspace, [client_dto(NIKE, "Nike")])
        nike = folder_of(NIKE)

        for lifecycle in ("active", "paused"):
            with zil_says(client_dto(NIKE, "Nike", lifecycle)):
                response = archive(session_client, workspace, project, nike)
            assert response.status_code == status.HTTP_400_BAD_REQUEST
            assert response.data["error_message"] == "ZIL_CLIENT_FOLDER_CLIENT_ACTIVE"
        assert folder_of(NIKE).archived_at is None

    @pytest.mark.django_db
    def test_the_folder_of_a_client_that_left_can_be_archived_and_stays_archived(
        self,
        session_client,
        workspace,
        project,
    ):
        push(None, workspace, [client_dto(NIKE, "Nike"), client_dto(ADIDAS, "Adidas")])
        nike = folder_of(NIKE)

        # the client churned and the next roster has not arrived yet
        with zil_says(client_dto(NIKE, "Nike", "churned")):
            response = archive(session_client, workspace, project, nike)
        assert response.status_code == status.HTTP_200_OK

        push(None, workspace, [client_dto(ADIDAS, "Adidas")])
        assert folder_of(NIKE).archived_at is not None

    @pytest.mark.django_db
    def test_zil_unreachable_archives_nothing(self, session_client, workspace, project):
        push(None, workspace, [client_dto(NIKE, "Nike")])
        with zil_says(ZilUnavailable()):
            response = archive(session_client, workspace, project, folder_of(NIKE))
        assert response.status_code == status.HTTP_502_BAD_GATEWAY
        assert folder_of(NIKE).archived_at is None


@pytest.mark.contract
class TestAutoFolderRestore:
    @pytest.mark.django_db
    def test_restoring_the_folder_of_a_client_that_left_is_refused(self, session_client, workspace, project):
        push(None, workspace, [client_dto(NIKE, "Nike"), client_dto(ADIDAS, "Adidas")])
        push(None, workspace, [client_dto(ADIDAS, "Adidas")])
        nike = folder_of(NIKE)
        assert nike.archived_at is not None

        # gone from the workspace's units, churned, or an onboarding that is not a sale yet (Zil says so)
        unsold = {**client_dto(NIKE, "Nike", "onboarding"), "opsFolder": False}
        for answer in (None, client_dto(NIKE, "Nike", "churned"), unsold):
            with zil_says(answer):
                response = restore(session_client, workspace, project, nike)
            assert response.status_code == status.HTTP_400_BAD_REQUEST
            assert response.data["error_message"] == "ZIL_CLIENT_FOLDER_CLIENT_LEFT"
        assert folder_of(NIKE).archived_at is not None

    @pytest.mark.django_db
    def test_a_folder_of_an_active_client_archived_with_its_parent_can_be_restored(
        self,
        session_client,
        workspace,
        project,
    ):
        push(None, workspace, [client_dto(NIKE, "Nike")])
        group = Page.objects.get(pk=create_folder(session_client, workspace, project, name="Grupo")["id"])
        move_in_tree(session_client, workspace, project, folder_of(NIKE), group)
        assert archive(session_client, workspace, project, group).status_code == status.HTTP_200_OK
        assert folder_of(NIKE).archived_at is not None

        with zil_says(client_dto(NIKE, "Nike")):
            response = restore(session_client, workspace, project, folder_of(NIKE))
        assert response.status_code == status.HTTP_200_OK
        assert folder_of(NIKE).archived_at is None


@pytest.mark.contract
class TestAutoFolderDelete:
    @pytest.mark.django_db
    def test_deleting_the_folder_of_an_active_client_is_refused(self, session_client, workspace, project):
        push(None, workspace, [client_dto(NIKE, "Nike")])
        nike = folder_of(NIKE)
        # archived along with a folder it was in, before the next roster brings it back
        Page.objects.filter(pk=nike.pk).update(archived_at="2026-10-01")

        with zil_says(client_dto(NIKE, "Nike")):
            response = delete(session_client, workspace, project, nike)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["error_message"] == "ZIL_CLIENT_FOLDER_CLIENT_ACTIVE"

        push(None, workspace, [client_dto(NIKE, "Nike")])
        assert folder_of(NIKE).pk == nike.pk and folder_of(NIKE).archived_at is None
        assert Page.objects.filter(name="Nike", kind=Page.FOLDER_KIND).count() == 1

    @pytest.mark.django_db
    def test_the_folder_of_a_client_that_left_can_be_deleted(self, session_client, workspace, project):
        push(None, workspace, [client_dto(NIKE, "Nike"), client_dto(ADIDAS, "Adidas")])
        push(None, workspace, [client_dto(ADIDAS, "Adidas")])
        nike = folder_of(NIKE)

        with zil_says(None):
            response = delete(session_client, workspace, project, nike)
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not PageZilClientLink.objects.filter(zil_client_id=NIKE).exists()


@pytest.mark.contract
class TestFoldersLinkedByHandKeepEveryAction:
    @pytest.mark.django_db
    def test_archive_restore_and_delete_without_asking_zil(self, session_client, workspace, project):
        manual = Page.objects.get(pk=create_folder(session_client, workspace, project, name="A mano")["id"])
        link_by_hand(session_client, workspace, project, manual, NIKE, "Nike")

        with zil_says(client_dto(NIKE, "Nike")) as lookup:
            assert archive(session_client, workspace, project, manual).status_code == status.HTTP_200_OK
            assert restore(session_client, workspace, project, manual).status_code == status.HTTP_200_OK
            assert archive(session_client, workspace, project, manual).status_code == status.HTTP_200_OK
            assert delete(session_client, workspace, project, manual).status_code == status.HTTP_204_NO_CONTENT
        lookup.assert_not_called()


@pytest.mark.contract
class TestAutoFolderPublicApi:
    """The external API (agents, integrations) follows the same rules as the app."""

    @pytest.mark.django_db
    def test_archive_and_restore_through_the_api_follow_the_roster(
        self, session_client, api_key_client, workspace, project
    ):
        push(None, workspace, [client_dto(NIKE, "Nike")])
        nike = folder_of(NIKE)
        url = f"/api/v1/workspaces/{workspace.slug}/projects/{project['id']}/pages/{nike.id}/archive/"

        with zil_says(client_dto(NIKE, "Nike")):
            refused = api_key_client.post(url)
        assert refused.status_code == status.HTTP_400_BAD_REQUEST
        assert refused.data["error_message"] == "ZIL_CLIENT_FOLDER_CLIENT_ACTIVE"
        assert folder_of(NIKE).archived_at is None

        with zil_says(None):
            assert api_key_client.post(url).status_code == status.HTTP_200_OK
            refused = api_key_client.delete(url)
        assert refused.status_code == status.HTTP_400_BAD_REQUEST
        assert refused.data["error_message"] == "ZIL_CLIENT_FOLDER_CLIENT_LEFT"
        assert folder_of(NIKE).archived_at is not None


@pytest.mark.contract
class TestArchiveStateOnlyThroughTheArchiveEndpoints:
    @pytest.mark.django_db
    def test_a_page_update_neither_archives_nor_restores_an_auto_folder(self, session_client, workspace, project):
        push(None, workspace, [client_dto(NIKE, "Nike"), client_dto(ADIDAS, "Adidas")])
        nike = folder_of(NIKE)

        with zil_says(client_dto(NIKE, "Nike")) as lookup:
            response = session_client.patch(
                pages_url(workspace, project, f"{nike.id}/"), {"archived_at": "2026-10-01"}, format="json"
            )
        assert response.status_code == status.HTTP_200_OK
        assert folder_of(NIKE).archived_at is None

        push(None, workspace, [client_dto(ADIDAS, "Adidas")])
        with zil_says(None):
            response = session_client.patch(
                pages_url(workspace, project, f"{nike.id}/"), {"archived_at": None}, format="json"
            )
        assert response.status_code == status.HTTP_200_OK
        assert folder_of(NIKE).archived_at is not None
        lookup.assert_not_called()

    @pytest.mark.django_db
    def test_a_plain_page_is_archived_and_restored_only_by_the_archive_endpoints(
        self, session_client, workspace, project
    ):
        # creating (also what duplicating a page sends) and updating ignore archived_at; the page comes back unarchived
        created = session_client.post(
            pages_url(workspace, project), {"name": "Notas", "archived_at": "2026-10-01"}, format="json"
        )
        assert created.status_code == status.HTTP_201_CREATED
        notes = Page.objects.get(pk=created.data["id"])
        assert notes.archived_at is None and created.data["archived_at"] is None

        patch = session_client.patch(
            pages_url(workspace, project, f"{notes.id}/"), {"archived_at": "2026-10-01"}, format="json"
        )
        assert patch.status_code == status.HTTP_200_OK and patch.data["archived_at"] is None
        assert Page.objects.get(pk=notes.pk).archived_at is None

        assert archive(session_client, workspace, project, notes).status_code == status.HTTP_200_OK
        archived_at = Page.objects.get(pk=notes.pk).archived_at
        assert archived_at is not None
        patch = session_client.patch(
            pages_url(workspace, project, f"{notes.id}/"), {"archived_at": None, "name": "Notas 2"}, format="json"
        )
        assert patch.status_code == status.HTTP_200_OK and patch.data["name"] == "Notas 2"
        assert Page.objects.get(pk=notes.pk).archived_at == archived_at

        assert restore(session_client, workspace, project, notes).status_code == status.HTTP_200_OK
        assert Page.objects.get(pk=notes.pk).archived_at is None


@pytest.mark.contract
class TestOtherPagesNeverAskZil:
    @pytest.mark.django_db
    def test_listing_costs_the_same_queries_with_one_client_folder_or_forty(self, session_client, workspace, project):
        def list_pages():
            with zil_says(ZilUnavailable()) as lookup, CaptureQueriesContext(connection) as queries:
                response = session_client.get(pages_url(workspace, project))
            assert response.status_code == status.HTTP_200_OK
            lookup.assert_not_called()
            return response.data, len(queries.captured_queries)

        push(None, workspace, [client_dto(f"{1:024x}", "Cliente 1")])
        few, few_queries = list_pages()
        push(None, workspace, [client_dto(f"{i:024x}", f"Cliente {i}") for i in range(1, 41)])
        many, many_queries = list_pages()

        assert (len(few), len(many)) == (2, 41)
        assert all(page["zil_client"]["auto_created"] for page in many if page["zil_client"])
        assert many_queries == few_queries

    @pytest.mark.django_db
    def test_zil_down_archives_restores_and_deletes_a_plain_page(self, session_client, workspace, project):
        push(None, workspace, [client_dto(NIKE, "Nike")])
        notes = Page.objects.get(pk=create_folder(session_client, workspace, project, name="Notas")["id"])

        with zil_says(ZilUnavailable()) as lookup:
            assert archive(session_client, workspace, project, notes).status_code == status.HTTP_200_OK
            assert restore(session_client, workspace, project, notes).status_code == status.HTTP_200_OK
            assert archive(session_client, workspace, project, notes).status_code == status.HTTP_200_OK
            assert delete(session_client, workspace, project, notes).status_code == status.HTTP_204_NO_CONTENT
        lookup.assert_not_called()


@pytest.mark.contract
class TestZilDecidesWhoKeepsAFolder:
    """Zil sends `opsFolder` (sold onboarding, paused within the grace period): it wins over the status."""

    @pytest.mark.django_db
    def test_a_paused_client_past_its_grace_can_be_archived_and_not_restored(self, session_client, workspace, project):
        push(None, workspace, [client_dto(NIKE, "Nike")])
        nike = folder_of(NIKE)
        past_grace = {**client_dto(NIKE, "Nike", "paused"), "opsFolder": False}

        with zil_says(past_grace):
            assert archive(session_client, workspace, project, nike).status_code == status.HTTP_200_OK
            refused = restore(session_client, workspace, project, nike)
        assert refused.data["error_message"] == "ZIL_CLIENT_FOLDER_CLIENT_LEFT"

    @pytest.mark.django_db
    def test_a_sold_onboarding_client_keeps_its_folder(self, session_client, workspace, project):
        push(None, workspace, [client_dto(NIKE, "Nike", "onboarding")])
        nike = folder_of(NIKE)

        with zil_says({**client_dto(NIKE, "Nike", "onboarding"), "opsFolder": True}):
            refused = archive(session_client, workspace, project, nike)
        assert refused.data["error_message"] == "ZIL_CLIENT_FOLDER_CLIENT_ACTIVE"
        assert folder_of(NIKE).archived_at is None

    @pytest.mark.django_db
    def test_an_older_zil_without_opsfolder_still_counts_onboarding_and_paused(
        self, session_client, workspace, project
    ):
        push(None, workspace, [client_dto(NIKE, "Nike")])
        nike = folder_of(NIKE)
        for lifecycle in ("onboarding", "paused"):
            with zil_says(client_dto(NIKE, "Nike", lifecycle)):
                refused = archive(session_client, workspace, project, nike)
            assert refused.data["error_message"] == "ZIL_CLIENT_FOLDER_CLIENT_ACTIVE"
