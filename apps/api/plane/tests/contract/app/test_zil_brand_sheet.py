# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from unittest import mock

import pytest
from rest_framework import status

from plane.db.models import Project, ProjectMember, ZilBrandProject
from plane.utils.zil_brand_projects import apply_brand_roster

KFC = "0123456789abcdef0123d001"
WENDYS = "0123456789abcdef0123d002"
ZIL_ENV = {"ZIL_BASE_URL": "http://zil.test", "ZIL_SERVICE_SECRET": "secret"}


@pytest.fixture
def brands(workspace, create_user):
    apply_brand_roster(
        workspace.id,
        [{"brandId": KFC, "name": "KFC", "logo": "https://zil.test/kfc.png"}, {"brandId": WENDYS, "name": "Wendy's"}],
        authoritative=True,
    )
    kfc = ZilBrandProject.objects.get(zil_brand_id=KFC).project
    ProjectMember.objects.create(project=kfc, member=create_user, role=20)
    return kfc


def fake_response(status_code, body):
    response = mock.Mock(status_code=status_code)
    response.json.return_value = body
    return response


@pytest.mark.contract
class TestMyBrands:
    @pytest.mark.django_db
    def test_lists_only_the_brands_the_person_is_on(self, session_client, workspace, brands):
        response = session_client.get(f"/api/workspaces/{workspace.slug}/zil-brands/")
        assert response.status_code == status.HTTP_200_OK
        assert [b["brand_id"] for b in response.data] == [KFC]
        assert response.data[0]["logo_url"] == "https://zil.test/kfc.png"
        assert response.data[0]["identifier"] == "KFC"


@pytest.mark.contract
class TestBrandSheet:
    @pytest.mark.django_db
    def test_the_sheet_is_read_live_as_the_person_and_carries_no_client_data(self, session_client, workspace, brands):
        body = {
            "brand": {
                "id": KFC,
                "name": "KFC",
                "logoUrl": None,
                "color": "#E2231A",
                "status": "active",
                "companyName": "X",
            },
            "specs": {"strip": [{"key": "pauta", "label": "Pauta", "value": "USD 1.200"}], "items": []},
            "assets": [{"id": "a1", "type": "drive_folder", "name": "Drive", "url": None, "companyName": "DEGASA SA"}],
            "team": [{"name": "Ana", "email": "ana@zil.global", "role": None, "taxId": "30-1"}],
            "calls": [{"id": "c1", "title": "Kickoff", "date": "2026-10-14", "client": {"companyName": "DEGASA SA"}}],
            "projects": [{"workspaceSlug": "zil-design", "businessUnit": "Zil Design", "clientName": "DEGASA SA"}],
            "client": {"companyName": "DEGASA SA"},
        }
        with (
            mock.patch.dict("os.environ", ZIL_ENV),
            mock.patch("plane.utils.zil_client.requests.get", return_value=fake_response(200, body)) as get,
        ):
            response = session_client.get(f"/api/workspaces/{workspace.slug}/projects/{brands.id}/zil-brand/")

        assert response.status_code == status.HTTP_200_OK
        assert get.call_args.args[0] == f"http://zil.test/api/sso/brands/{KFC}"
        assert get.call_args.kwargs["params"] == {"workspaceSlug": workspace.slug, "actor": "test@plane.so"}
        sheet = response.data["sheet"]
        assert sheet["specs"]["strip"][0]["value"] == "USD 1.200" and sheet["team"][0]["name"] == "Ana"
        assert "client" not in sheet and "companyName" not in sheet["brand"]
        # nested rows keep only their own fields: nothing of the client slips through
        assert "companyName" not in str(response.data) and "DEGASA" not in str(response.data)
        assert "taxId" not in str(response.data) and sheet["calls"][0]["title"] == "Kickoff"

    @pytest.mark.django_db
    def test_zil_down_still_shows_the_brand(self, session_client, workspace, brands):
        with (
            mock.patch.dict("os.environ", ZIL_ENV),
            mock.patch("plane.utils.zil_client.requests.get", side_effect=TimeoutError()),
        ):
            response = session_client.get(f"/api/workspaces/{workspace.slug}/projects/{brands.id}/zil-brand/")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["unavailable"] is True and response.data["brand"]["name"] == "KFC"

    @pytest.mark.django_db
    def test_zil_saying_no_shows_no_sheet(self, session_client, workspace, brands):
        with (
            mock.patch.dict("os.environ", ZIL_ENV),
            mock.patch("plane.utils.zil_client.requests.get", return_value=fake_response(404, {})),
        ):
            response = session_client.get(f"/api/workspaces/{workspace.slug}/projects/{brands.id}/zil-brand/")
        assert response.status_code == status.HTTP_200_OK and response.data["sheet"] is None

    @pytest.mark.django_db
    def test_a_project_that_is_not_a_brand_has_no_sheet(self, session_client, workspace, create_user):
        project = Project.objects.create(workspace=workspace, name="Interno", identifier="INT")
        ProjectMember.objects.create(project=project, member=create_user, role=20)
        response = session_client.get(f"/api/workspaces/{workspace.slug}/projects/{project.id}/zil-brand/")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.django_db
    def test_a_non_member_cannot_read_a_brand(self, session_client, workspace, brands):
        wendys = ZilBrandProject.objects.get(zil_brand_id=WENDYS).project
        response = session_client.get(f"/api/workspaces/{workspace.slug}/projects/{wendys.id}/zil-brand/")
        assert response.status_code in (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND)
