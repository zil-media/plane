# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from unittest import mock

import pytest
from rest_framework import status

from plane.db.models import Project, ProjectMember, User, WorkspaceMember, ZilBrandProject
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
    # the workspace admin of the fixtures is on every brand; here they stay only on KFC
    wendys = ZilBrandProject.objects.get(zil_brand_id=WENDYS).project
    ProjectMember.objects.filter(project=wendys, member=create_user).update(is_active=False)
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
            "files": [
                {"id": "f1", "name": "Logo", "type": "image/png", "url": "https://r2.test/logo", "key": "DEGASA/logo"}
            ],
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
        assert sheet["files"] == [{"id": "f1", "name": "Logo", "type": "image/png", "url": "https://r2.test/logo"}]

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


@pytest.fixture
def teammate(workspace, brands):
    user = User.objects.create(email="cm@zil.global", username="cm", display_name="Carla")
    WorkspaceMember.objects.create(workspace=workspace, member=user, role=15)
    ProjectMember.objects.create(project=brands, member=user, role=15, workspace=workspace)
    return user


@pytest.mark.contract
class TestBrandOpsFields:
    def url(self, workspace, project):
        return f"/api/workspaces/{workspace.slug}/projects/{project.id}/zil-brand/"

    def get_ops(self, client, workspace, project):
        with mock.patch.dict("os.environ", {"ZIL_BASE_URL": "", "ZIL_SERVICE_SECRET": ""}):
            return client.get(self.url(workspace, project)).data["ops"]

    @pytest.mark.django_db
    def test_several_cms_leaders_and_drive_links_are_loaded_from_ops_and_shown(
        self, session_client, workspace, brands, create_user, teammate
    ):
        body = {
            "community_manager_ids": [str(create_user.id), str(teammate.id)],
            "leader_ids": [str(teammate.id)],
            "materials_links": [
                {"name": " Fotos ", "url": " https://drive.google.com/drive/folders/fotos "},
                {"url": "https://drive.google.com/drive/folders/logos"},
            ],
            "finals_links": [{"name": "Octubre", "url": "https://drive.google.com/drive/folders/octubre"}],
        }
        response = session_client.patch(self.url(workspace, brands), body, format="json")
        assert response.status_code == status.HTTP_200_OK, response.data

        ops = self.get_ops(session_client, workspace, brands)
        assert set(ops["community_manager_ids"]) == {str(create_user.id), str(teammate.id)}
        assert ops["leader_ids"] == [str(teammate.id)]
        assert ops["materials_links"] == [
            {"name": "Fotos", "url": "https://drive.google.com/drive/folders/fotos"},
            {"name": "", "url": "https://drive.google.com/drive/folders/logos"},
        ]
        assert ops["finals_links"] == [{"name": "Octubre", "url": "https://drive.google.com/drive/folders/octubre"}]

        # each field sent replaces its whole list; the rest stay as they were
        cleared = session_client.patch(
            self.url(workspace, brands), {"leader_ids": [], "finals_links": []}, format="json"
        )
        assert cleared.data["ops"]["leader_ids"] == [] and cleared.data["ops"]["finals_links"] == []
        assert (
            len(cleared.data["ops"]["community_manager_ids"]) == 2 and len(cleared.data["ops"]["materials_links"]) == 2
        )

    @pytest.mark.django_db
    def test_only_project_members_and_http_links_are_accepted(self, session_client, workspace, brands, create_user):
        outsider = User.objects.create(email="out@zil.global", username="out")
        response = session_client.patch(
            self.url(workspace, brands),
            {
                "community_manager_ids": [str(create_user.id), str(outsider.id)],
                "leader_ids": ["not-a-uuid"],
                "materials_links": [
                    {"name": "ok", "url": "https://drive.google.com/a"},
                    {"url": "javascript:alert(1)"},
                ],
                "finals_links": "https://drive.google.com/b",
            },
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert set(response.data) == {"community_manager_ids", "leader_ids", "materials_links", "finals_links"}
        mapping = ZilBrandProject.objects.get(zil_brand_id=KFC)
        assert not mapping.community_managers.exists() and mapping.materials_links == []

    @pytest.mark.django_db
    def test_someone_off_the_brand_team_stops_showing_and_shows_again_on_return(
        self, session_client, workspace, brands, teammate
    ):
        session_client.patch(self.url(workspace, brands), {"community_manager_ids": [str(teammate.id)]}, format="json")
        ProjectMember.objects.filter(project=brands, member=teammate).update(is_active=False)
        assert self.get_ops(session_client, workspace, brands)["community_manager_ids"] == []
        ProjectMember.objects.filter(project=brands, member=teammate).update(is_active=True)
        assert self.get_ops(session_client, workspace, brands)["community_manager_ids"] == [str(teammate.id)]

    @pytest.mark.django_db
    def test_a_guest_reads_but_cannot_edit(self, session_client, workspace, brands, create_user):
        # a workspace admin edits every project they are on, whatever their project role
        WorkspaceMember.objects.filter(workspace=workspace, member=create_user).update(role=5)
        ProjectMember.objects.filter(project=brands, member=create_user).update(role=5)
        with mock.patch.dict("os.environ", {"ZIL_BASE_URL": "", "ZIL_SERVICE_SECRET": ""}):
            assert session_client.get(self.url(workspace, brands)).status_code == status.HTTP_200_OK
        response = session_client.patch(self.url(workspace, brands), {"finals_links": []}, format="json")
        assert response.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.django_db
    def test_the_roster_sync_keeps_what_ops_loaded(self, session_client, workspace, brands, create_user):
        link = [{"name": "", "url": "https://drive.google.com/f"}]
        session_client.patch(
            self.url(workspace, brands), {"leader_ids": [str(create_user.id)], "finals_links": link}, format="json"
        )
        apply_brand_roster(
            workspace.id,
            [{"brandId": KFC, "name": "KFC Argentina"}, {"brandId": WENDYS, "name": "Wendy's"}],
            authoritative=True,
        )
        mapping = ZilBrandProject.objects.get(zil_brand_id=KFC)
        assert list(mapping.leaders.all()) == [create_user] and mapping.finals_links == link
