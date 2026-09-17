# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from unittest import mock

import pytest
from rest_framework import status

from plane.db.models import Page, PageZilClientLink

CLIENT_ID = "0123456789abcdef01234567"


@pytest.fixture(autouse=True)
def no_background_tasks():
    with (
        mock.patch("plane.app.views.page.base.page_transaction.delay"),
        mock.patch("plane.app.views.page.base.recent_visited_task.delay"),
        mock.patch("plane.app.views.page.base.refresh_zil_client_link.delay"),
    ):
        yield


@pytest.fixture
def project(session_client, workspace):
    response = session_client.post(
        f"/api/workspaces/{workspace.slug}/projects/",
        {"name": "Tree Project", "identifier": "TRP"},
        format="json",
    )
    assert response.status_code == status.HTTP_201_CREATED
    return response.data


def pages_url(workspace, project, suffix=""):
    return f"/api/workspaces/{workspace.slug}/projects/{project['id']}/pages/{suffix}"


def create_page(client, workspace, project, **data):
    response = client.post(pages_url(workspace, project), {"name": "Page", **data}, format="json")
    assert response.status_code == status.HTTP_201_CREATED, response.data
    return response.data


def move(client, workspace, project, page_id, parent_id):
    return client.post(
        pages_url(workspace, project, f"{page_id}/move-in-tree/"),
        {"parent_id": parent_id},
        format="json",
    )


@pytest.mark.contract
class TestPageTree:
    @pytest.mark.django_db
    def test_list_returns_nested_pages(self, session_client, workspace, project):
        folder = create_page(session_client, workspace, project, name="Client", kind="folder")
        child = create_page(session_client, workspace, project, name="Brief", parent=folder["id"])

        response = session_client.get(pages_url(workspace, project))
        assert response.status_code == status.HTTP_200_OK
        by_id = {str(p["id"]): p for p in response.data}
        assert str(child["id"]) in by_id
        assert str(by_id[str(child["id"])]["parent"]) == str(folder["id"])
        assert by_id[str(folder["id"])]["kind"] == "folder"

        roots = session_client.get(pages_url(workspace, project), {"parent": "root"}).data
        assert {str(p["id"]) for p in roots} == {str(folder["id"])}

    @pytest.mark.django_db
    def test_children_are_appended_after_siblings(self, session_client, workspace, project):
        folder = create_page(session_client, workspace, project, kind="folder")
        first = create_page(session_client, workspace, project, parent=folder["id"])
        second = create_page(session_client, workspace, project, parent=folder["id"])
        assert second["sort_order"] > first["sort_order"]

    @pytest.mark.django_db
    def test_create_with_unknown_parent_fails(self, session_client, workspace, project):
        response = session_client.post(
            pages_url(workspace, project),
            {"name": "Orphan", "parent": "00000000-0000-0000-0000-000000000000"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["error_message"] == "PAGE_PARENT_INVALID"

    @pytest.mark.django_db
    def test_move_into_own_descendant_is_rejected(self, session_client, workspace, project):
        a = create_page(session_client, workspace, project, name="A")
        b = create_page(session_client, workspace, project, name="B", parent=a["id"])

        response = move(session_client, workspace, project, a["id"], b["id"])
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["error_message"] == "PAGE_TREE_CYCLE"

        response = move(session_client, workspace, project, a["id"], a["id"])
        assert response.data["error_message"] == "PAGE_TREE_CYCLE"

    @pytest.mark.django_db
    def test_move_to_root_and_under_page(self, session_client, workspace, project):
        a = create_page(session_client, workspace, project, name="A")
        b = create_page(session_client, workspace, project, name="B")

        response = move(session_client, workspace, project, b["id"], a["id"])
        assert response.status_code == status.HTTP_200_OK
        assert str(Page.objects.get(pk=b["id"]).parent_id) == str(a["id"])

        response = move(session_client, workspace, project, b["id"], None)
        assert response.status_code == status.HTTP_200_OK
        assert Page.objects.get(pk=b["id"]).parent_id is None

    @pytest.mark.django_db
    def test_depth_limit(self, session_client, workspace, project):
        parent_id = None
        for level in range(Page.MAX_TREE_DEPTH):
            data = {"name": f"L{level}"}
            if parent_id:
                data["parent"] = parent_id
            parent_id = create_page(session_client, workspace, project, **data)["id"]

        response = session_client.post(
            pages_url(workspace, project), {"name": "too deep", "parent": parent_id}, format="json"
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["error_message"] == "PAGE_TREE_DEPTH"

    @pytest.mark.django_db
    def test_archive_folder_archives_subtree(self, session_client, workspace, project):
        folder = create_page(session_client, workspace, project, kind="folder")
        child = create_page(session_client, workspace, project, parent=folder["id"])
        grandchild = create_page(session_client, workspace, project, parent=child["id"])

        response = session_client.post(pages_url(workspace, project, f"{folder['id']}/archive/"))
        assert response.status_code == status.HTTP_200_OK
        assert {str(i) for i in response.data["archived_page_ids"]} == {
            str(folder["id"]),
            str(child["id"]),
            str(grandchild["id"]),
        }

        response = session_client.delete(pages_url(workspace, project, f"{folder['id']}/archive/"))
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["restored_page_ids"]) == 3
        assert Page.objects.filter(archived_at__isnull=False).count() == 0

    @pytest.mark.django_db
    def test_delete_moves_children_to_grandparent(self, session_client, workspace, project):
        root = create_page(session_client, workspace, project, kind="folder")
        middle = create_page(session_client, workspace, project, kind="folder", parent=root["id"])
        leaf = create_page(session_client, workspace, project, parent=middle["id"])

        session_client.post(pages_url(workspace, project, f"{middle['id']}/archive/"))
        response = session_client.delete(pages_url(workspace, project, f"{middle['id']}/"))
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert str(Page.objects.get(pk=leaf["id"]).parent_id) == str(root["id"])

    @pytest.mark.django_db
    def test_folder_has_no_content_and_kind_is_immutable(self, session_client, workspace, project):
        folder = create_page(session_client, workspace, project, kind="folder", description_html="<p>x</p>")
        assert Page.objects.get(pk=folder["id"]).description_html == "<p></p>"

        response = session_client.patch(
            pages_url(workspace, project, f"{folder['id']}/description/"),
            {"description_html": "<p>nope</p>"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["error_message"] == "PAGE_IS_FOLDER"

        response = session_client.patch(
            pages_url(workspace, project, f"{folder['id']}/"), {"kind": "page"}, format="json"
        )
        assert response.status_code == status.HTTP_200_OK
        assert Page.objects.get(pk=folder["id"]).kind == "folder"

        response = session_client.post(pages_url(workspace, project, f"{folder['id']}/lock/"))
        assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.contract
class TestPageZilClientLink:
    def zil_env(self):
        return mock.patch.dict(
            "os.environ", {"ZIL_BASE_URL": "http://zil.test", "ZIL_SERVICE_SECRET": "secret"}
        )

    @pytest.mark.django_db
    def test_search_disabled_without_env(self, session_client, workspace, project):
        with mock.patch.dict("os.environ", {"ZIL_BASE_URL": "", "ZIL_SERVICE_SECRET": ""}):
            response = session_client.get(f"/api/workspaces/{workspace.slug}/projects/{project['id']}/zil-clients/")
        assert response.status_code == status.HTTP_200_OK
        assert response.data == {"enabled": False, "results": []}

    @pytest.mark.django_db
    def test_link_folder_and_conflict(self, session_client, workspace, project):
        folder = create_page(session_client, workspace, project, kind="folder")
        other = create_page(session_client, workspace, project, kind="folder")
        page = create_page(session_client, workspace, project)
        client = {"id": CLIENT_ID, "alias": "Nike", "companyName": "Nike SA", "lifecycleStatus": "active"}

        with self.zil_env(), mock.patch("plane.app.views.page.zil_client.get_zil_client", return_value=client):
            url = pages_url(workspace, project, f"{folder['id']}/zil-client/")
            response = session_client.post(url, {"zil_client_id": CLIENT_ID}, format="json")
            assert response.status_code == status.HTTP_200_OK
            assert response.data["alias"] == "Nike"

            response = session_client.post(
                pages_url(workspace, project, f"{other['id']}/zil-client/"),
                {"zil_client_id": CLIENT_ID},
                format="json",
            )
            assert response.status_code == status.HTTP_409_CONFLICT
            assert str(response.data["page_id"]) == str(folder["id"])

            response = session_client.post(
                pages_url(workspace, project, f"{page['id']}/zil-client/"),
                {"zil_client_id": CLIENT_ID},
                format="json",
            )
            assert response.status_code == status.HTTP_400_BAD_REQUEST

        detail = session_client.get(pages_url(workspace, project, f"{folder['id']}/"))
        assert detail.data["zil_client"]["company_name"] == "Nike SA"

        response = session_client.delete(pages_url(workspace, project, f"{folder['id']}/zil-client/"))
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert PageZilClientLink.all_objects.count() == 0

    @pytest.mark.django_db
    def test_link_rejects_client_outside_workspace(self, session_client, workspace, project):
        folder = create_page(session_client, workspace, project, kind="folder")
        with self.zil_env(), mock.patch("plane.app.views.page.zil_client.get_zil_client", return_value=None):
            response = session_client.post(
                pages_url(workspace, project, f"{folder['id']}/zil-client/"),
                {"zil_client_id": CLIENT_ID},
                format="json",
            )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["error_message"] == "ZIL_CLIENT_NOT_FOUND"
