# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from unittest import mock

import pytest
from rest_framework import status

from plane.db.models import Issue, ProjectMember, User, WorkspaceMember
from plane.utils.zil_client import ZilUnavailable

CLIENT_ID = "0123456789abcdef01234567"
ZIL_ENV = {"ZIL_BASE_URL": "http://zil.test", "ZIL_SERVICE_SECRET": "secret"}
REFS = {
    "client": {"id": CLIENT_ID, "name": "Joyas Esmeralda", "url": "http://zil.test/c"},
    "project": None,
}


@pytest.fixture
def project(session_client, workspace):
    response = session_client.post(
        f"/api/workspaces/{workspace.slug}/projects/",
        {"name": "Clients Project", "identifier": "CLP"},
        format="json",
    )
    assert response.status_code == status.HTTP_201_CREATED
    return response.data


@pytest.fixture
def issue(workspace, project, create_user):
    return Issue.objects.create(
        workspace=workspace, project_id=project["id"], name="Campaña", created_by=create_user
    )


@pytest.fixture
def zil_env():
    with mock.patch.dict("os.environ", ZIL_ENV):
        yield


@pytest.mark.contract
class TestZilErpOptions:
    @pytest.mark.django_db
    def test_client_options_are_mapped_from_zil(self, session_client, workspace, zil_env):
        clients = [
            {"id": CLIENT_ID, "alias": "Joyas", "companyName": "Joyas Esmeralda SA"},
            {"id": "0123456789abcdef01234568", "alias": "", "companyName": "Auraluxe"},
        ]
        with mock.patch(
            "plane.authentication.views.zil_sync.search_zil_clients", return_value=clients
        ) as search:
            response = session_client.get(
                "/api/zil/erp-options/", {"workspace_slug": workspace.slug, "kind": "client"}
            )
        assert response.status_code == status.HTTP_200_OK
        search.assert_called_once_with(workspace.slug, "", 200)
        assert response.data["options"] == [
            {"id": CLIENT_ID, "name": "Joyas", "subtitle": "Joyas Esmeralda SA"},
            {"id": "0123456789abcdef01234568", "name": "Auraluxe", "subtitle": ""},
        ]

    @pytest.mark.django_db
    def test_project_options_carry_client_and_service(self, session_client, workspace, zil_env):
        projects = [{"id": CLIENT_ID, "name": "SEO 2026", "clientName": "Joyas", "brand": "", "service": "SEO"}]
        with mock.patch("plane.authentication.views.zil_sync.search_zil_projects", return_value=projects):
            response = session_client.get(
                "/api/zil/erp-options/", {"workspace_slug": workspace.slug, "kind": "project"}
            )
        assert response.data["options"] == [{"id": CLIENT_ID, "name": "SEO 2026", "subtitle": "Joyas · SEO"}]

    @pytest.mark.django_db
    def test_non_member_gets_404(self, session_client, zil_env):
        response = session_client.get("/api/zil/erp-options/", {"workspace_slug": "other", "kind": "client"})
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.django_db
    def test_zil_down_is_502(self, session_client, workspace, zil_env):
        with mock.patch("plane.authentication.views.zil_sync.search_zil_clients", side_effect=ZilUnavailable):
            response = session_client.get(
                "/api/zil/erp-options/", {"workspace_slug": workspace.slug, "kind": "client"}
            )
        assert response.status_code == status.HTTP_502_BAD_GATEWAY


@pytest.mark.contract
class TestZilIssueErpRefs:
    @pytest.mark.django_db
    def test_read_relays_the_erp_links(self, session_client, workspace, issue, zil_env):
        with mock.patch(
            "plane.authentication.views.zil_sync.get_issue_erp_refs", return_value=REFS
        ) as get_refs:
            response = session_client.get("/api/zil/issue-erp-refs/", {"issue_id": str(issue.id)})
        assert response.status_code == status.HTTP_200_OK
        get_refs.assert_called_once_with(workspace.slug, str(issue.id))
        assert response.data == REFS

    @pytest.mark.django_db
    def test_set_asks_zil_with_the_actor(self, session_client, workspace, issue, create_user, zil_env):
        with mock.patch(
            "plane.authentication.views.zil_sync.set_issue_erp_ref", return_value=REFS
        ) as set_ref:
            response = session_client.post(
                "/api/zil/issue-erp-refs/",
                {"issue_id": str(issue.id), "kind": "client", "erp_id": CLIENT_ID},
                format="json",
            )
        assert response.status_code == status.HTTP_200_OK
        set_ref.assert_called_once_with(
            {
                "kind": "client",
                "erp_id": CLIENT_ID,
                "workspace_slug": workspace.slug,
                "plane_issue_id": str(issue.id),
                "actor_email": create_user.email,
            }
        )
        assert response.data == REFS

    @pytest.mark.django_db
    def test_entity_outside_the_workspace_is_404(self, session_client, issue, zil_env):
        with mock.patch("plane.authentication.views.zil_sync.set_issue_erp_ref", return_value=None):
            response = session_client.post(
                "/api/zil/issue-erp-refs/",
                {"issue_id": str(issue.id), "kind": "project", "erp_id": CLIENT_ID},
                format="json",
            )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.django_db
    def test_invalid_kind_or_id_is_400(self, session_client, issue, zil_env):
        for body in ({"kind": "lead", "erp_id": CLIENT_ID}, {"kind": "client", "erp_id": "nope"}):
            response = session_client.post(
                "/api/zil/issue-erp-refs/", {"issue_id": str(issue.id), **body}, format="json"
            )
            assert response.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.django_db
    def test_guest_can_read_but_not_change(self, api_client, workspace, issue, zil_env):
        guest = User.objects.create(email="guest@zil.test", username="guest")
        WorkspaceMember.objects.create(workspace=workspace, member=guest, role=5)
        ProjectMember.objects.create(workspace=workspace, project_id=issue.project_id, member=guest, role=5)
        api_client.force_authenticate(user=guest)
        with (
            mock.patch("plane.authentication.views.zil_sync.get_issue_erp_refs", return_value=REFS),
            mock.patch("plane.authentication.views.zil_sync.set_issue_erp_ref") as set_ref,
        ):
            assert api_client.get("/api/zil/issue-erp-refs/", {"issue_id": str(issue.id)}).status_code == 200
            response = api_client.post(
                "/api/zil/issue-erp-refs/",
                {"issue_id": str(issue.id), "kind": "client", "erp_id": None},
                format="json",
            )
        assert response.status_code == status.HTTP_404_NOT_FOUND
        set_ref.assert_not_called()
