# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from unittest import mock

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from plane.authentication.views.zil_sync import ZilErpLinksEndpoint
from plane.db.models import Page, ProjectMember, ProjectPage, User, WorkspaceMember, ZilBrandProject
from plane.utils.zil_brand_projects import apply_brand_roster

KFC = "0123456789abcdef0123e001"


@pytest.fixture
def brand_page(workspace, create_user):
    apply_brand_roster(workspace.id, [{"brandId": KFC, "name": "KFC"}], authoritative=True)
    project = ZilBrandProject.objects.get(zil_brand_id=KFC).project
    page = Page.objects.create(
        workspace=workspace, name="Brief KFC", owned_by=create_user, external_source="zil", external_id="x"
    )
    ProjectPage.objects.create(workspace=workspace, project=project, page=page)
    return project, page


def links(client, page):
    return client.get("/api/zil/erp-links/", {"entity_type": "page", "entity_id": str(page.id)})


@pytest.mark.contract
class TestErpLinksPageScope:
    @pytest.mark.django_db
    def test_a_page_of_a_brand_one_is_not_on_is_not_found(self, session_client, brand_page):
        # the workspace admin of the fixtures is in the workspace but not on the brand
        _, page = brand_page
        assert links(session_client, page).status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.django_db
    def test_a_member_of_the_page_project_gets_its_links(self, session_client, brand_page, create_user):
        project, page = brand_page
        ProjectMember.objects.create(project=project, member=create_user, role=20)
        response = links(session_client, page)
        assert response.status_code == status.HTTP_200_OK and response.data == {"links": []}

    @pytest.mark.django_db
    def test_the_chip_asks_zil_as_the_person_looking_and_does_not_share_the_answer(
        self, session_client, workspace, brand_page, create_user
    ):
        project, page = brand_page
        ProjectMember.objects.create(project=project, member=create_user, role=20)
        ana = User.objects.create(email="ana@zil.global", username="ana")
        WorkspaceMember.objects.create(workspace=workspace, member=ana, role=15)
        ProjectMember.objects.create(project=project, member=ana, role=15)
        ana_client = APIClient()
        ana_client.force_authenticate(user=ana)
        ZilErpLinksEndpoint._CACHE.clear()

        answer = mock.Mock(status_code=200, json=lambda: {"links": []})
        env = {"ZIL_BASE_URL": "http://zil.test", "ZIL_SERVICE_SECRET": "secret"}
        with (
            mock.patch.dict("os.environ", env),
            mock.patch("plane.authentication.views.zil_sync.requests.get", return_value=answer) as get,
        ):
            assert links(session_client, page).status_code == status.HTTP_200_OK
            assert links(ana_client, page).status_code == status.HTTP_200_OK

        # one call per person: what Zil showed one is never served to the other from the memo
        assert [c.kwargs["params"] for c in get.call_args_list] == [
            {"plane_entity_id": str(page.id), "workspace_slug": workspace.slug, "actor_email": create_user.email},
            {"plane_entity_id": str(page.id), "workspace_slug": workspace.slug, "actor_email": "ana@zil.global"},
        ]
