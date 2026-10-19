# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import pytest
from rest_framework import status

from plane.db.models import Page, ProjectMember, ProjectPage, ZilBrandProject
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
