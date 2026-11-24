# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from unittest import mock

import pytest
from django.utils import timezone
from rest_framework import status

from plane.db.models import (
    Project,
    ProjectMember,
    User,
    Workspace,
    WorkspaceMember,
    ZilBrandOps,
    ZilBrandProject,
    ZilBrandResponsible,
)
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
    def test_several_cms_a_responsable_and_drive_links_are_loaded_from_ops_and_shown(
        self, session_client, workspace, brands, create_user, teammate
    ):
        body = {
            "community_manager_ids": [str(create_user.id), str(teammate.id)],
            "responsibles": [{"workspace_id": str(workspace.id), "member_id": str(teammate.id)}],
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
        assert ops["responsibles"] == [
            {"workspace_id": str(workspace.id), "business_unit": workspace.name, "member_id": str(teammate.id)}
        ]
        assert ops["materials_links"] == [
            {"name": "Fotos", "url": "https://drive.google.com/drive/folders/fotos"},
            {"name": "", "url": "https://drive.google.com/drive/folders/logos"},
        ]
        assert ops["finals_links"] == [{"name": "Octubre", "url": "https://drive.google.com/drive/folders/octubre"}]

        # each field sent replaces its whole list; the rest stay as they were
        unset = [{"workspace_id": str(workspace.id), "member_id": None}]
        cleared = session_client.patch(
            self.url(workspace, brands), {"responsibles": unset, "finals_links": []}, format="json"
        )
        assert cleared.data["ops"]["responsibles"][0]["member_id"] is None
        assert cleared.data["ops"]["finals_links"] == []
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
                "responsibles": [{"workspace_id": str(workspace.id), "member_id": "not-a-uuid"}],
                "materials_links": [
                    {"name": "ok", "url": "https://drive.google.com/a"},
                    {"url": "javascript:alert(1)"},
                ],
                "finals_links": "https://drive.google.com/b",
            },
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert set(response.data) == {"community_manager_ids", "responsibles", "materials_links", "finals_links"}
        assert not ZilBrandOps.objects.filter(zil_brand_id=KFC).exists()

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
        unit = [{"workspace_id": str(workspace.id), "member_id": str(create_user.id)}]
        session_client.patch(self.url(workspace, brands), {"responsibles": unit, "finals_links": link}, format="json")
        apply_brand_roster(
            workspace.id,
            [{"brandId": KFC, "name": "KFC Argentina"}, {"brandId": WENDYS, "name": "Wendy's"}],
            authoritative=True,
        )
        ops = ZilBrandOps.objects.get(zil_brand_id=KFC)
        assert ops.finals_links == link
        assert ZilBrandResponsible.objects.get(zil_brand_id=KFC, workspace=workspace).member == create_user


    @pytest.mark.django_db
    def test_a_cm_who_never_signed_in_is_on_the_team_and_can_be_picked(self, session_client, workspace, brands):
        apply_brand_roster(
            workspace.id,
            [
                {"brandId": KFC, "name": "KFC", "members": [{"email": "andreina@zil.global"}]},
                {"brandId": WENDYS, "name": "Wendy's"},
            ],
            authoritative=True,
        )
        cm = User.objects.get(email="andreina@zil.global")
        assert str(cm.id) in [person["id"] for person in self.get_ops(session_client, workspace, brands)["team"]]

        body = {"community_manager_ids": [str(cm.id)]}
        response = session_client.patch(self.url(workspace, brands), body, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert response.data["ops"]["community_manager_ids"] == [str(cm.id)]


@pytest.fixture
def meraki(brands, create_user):
    """Meraki's workspace also works KFC: its own KFC project, with its own CM on it."""
    workspace = Workspace.objects.create(name="Meraki", slug="meraki", owner=create_user)
    WorkspaceMember.objects.create(workspace=workspace, member=create_user, role=20)
    apply_brand_roster(workspace.id, [{"brandId": KFC, "name": "KFC"}], authoritative=True)
    project = ZilBrandProject.objects.get(workspace=workspace, zil_brand_id=KFC).project
    cm = User.objects.create(
        email="cm@meraki.ar", username="cm-meraki", display_name="Mora", avatar="https://x.test/m.png"
    )
    WorkspaceMember.objects.create(workspace=workspace, member=cm, role=15)
    ProjectMember.objects.create(project=project, member=cm, role=15, workspace=workspace)
    return workspace, project, cm


@pytest.mark.contract
class TestBrandOpsSharedAcrossUnits:
    def url(self, workspace, project):
        return f"/api/workspaces/{workspace.slug}/projects/{project.id}/zil-brand/"

    def get_ops(self, client, workspace, project):
        with mock.patch.dict("os.environ", {"ZIL_BASE_URL": "", "ZIL_SERVICE_SECRET": ""}):
            return client.get(self.url(workspace, project)).data["ops"]

    @pytest.mark.django_db
    def test_what_one_unit_loads_shows_in_every_workspace_of_the_brand(
        self, session_client, workspace, brands, meraki, create_user
    ):
        meraki_ws, meraki_kfc, meraki_cm = meraki
        # loaded from Zil's workspace, with Meraki's CM (on the brand only in Meraki's workspace)
        response = session_client.patch(
            self.url(workspace, brands),
            {
                "community_manager_ids": [str(meraki_cm.id)],
                "materials_links": [{"name": "Fotos", "url": "https://drive.google.com/drive/folders/fotos"}],
            },
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK, response.data
        assert response.data["ops"]["community_manager_ids"] == [str(meraki_cm.id)]

        seen_from_meraki = self.get_ops(session_client, meraki_ws, meraki_kfc)
        assert seen_from_meraki["community_manager_ids"] == [str(meraki_cm.id)]
        assert seen_from_meraki["materials_links"] == [
            {"name": "Fotos", "url": "https://drive.google.com/drive/folders/fotos"}
        ]

        # and a change from Meraki's workspace shows back in Zil's
        session_client.patch(
            self.url(meraki_ws, meraki_kfc), {"finals_links": [{"url": "https://d.test/f"}]}, format="json"
        )
        assert self.get_ops(session_client, workspace, brands)["finals_links"] == [
            {"name": "", "url": "https://d.test/f"}
        ]
        assert ZilBrandOps.objects.filter(zil_brand_id=KFC).count() == 1

    @pytest.mark.django_db
    def test_the_team_is_everyone_on_the_brand_in_every_workspace_with_their_photo(
        self, session_client, workspace, brands, meraki, create_user
    ):
        _, _, meraki_cm = meraki
        team = {person["email"]: person for person in self.get_ops(session_client, workspace, brands)["team"]}
        assert set(team) == {create_user.email, meraki_cm.email}
        assert team[meraki_cm.email]["avatar_url"] == "https://x.test/m.png"
        assert team[meraki_cm.email]["business_units"] == ["Meraki"]
        assert sorted(team[create_user.email]["business_units"]) == sorted([workspace.name, "Meraki"])

    @pytest.mark.django_db
    def test_someone_off_the_brand_in_every_workspace_cannot_be_picked(self, session_client, workspace, brands, meraki):
        _, meraki_kfc, meraki_cm = meraki
        ProjectMember.objects.filter(project=meraki_kfc, member=meraki_cm).update(is_active=False)
        response = session_client.patch(
            self.url(workspace, brands), {"community_manager_ids": [str(meraki_cm.id)]}, format="json"
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert meraki_cm.email not in [p["email"] for p in self.get_ops(session_client, workspace, brands)["team"]]

    @pytest.mark.django_db
    def test_each_unit_has_its_own_responsable_picked_among_who_works_the_brand_there(
        self, session_client, workspace, brands, meraki, create_user
    ):
        meraki_ws, meraki_kfc, meraki_cm = meraki
        body = {
            "responsibles": [
                {"workspace_id": str(workspace.id), "member_id": str(create_user.id)},
                {"workspace_id": str(meraki_ws.id), "member_id": str(meraki_cm.id)},
            ]
        }
        response = session_client.patch(self.url(workspace, brands), body, format="json")
        assert response.status_code == status.HTTP_200_OK, response.data

        expected = sorted(
            [
                {"workspace_id": str(meraki_ws.id), "business_unit": "Meraki", "member_id": str(meraki_cm.id)},
                {"workspace_id": str(workspace.id), "business_unit": workspace.name, "member_id": str(create_user.id)},
            ],
            key=lambda unit: unit["business_unit"],
        )
        assert self.get_ops(session_client, meraki_ws, meraki_kfc)["responsibles"] == expected

        # a change to one unit leaves the other's
        one = {"responsibles": [{"workspace_id": str(meraki_ws.id), "member_id": str(create_user.id)}]}
        session_client.patch(self.url(meraki_ws, meraki_kfc), one, format="json")
        by_unit = {
            unit["workspace_id"]: unit["member_id"]
            for unit in self.get_ops(session_client, workspace, brands)["responsibles"]
        }
        assert by_unit == {str(workspace.id): str(create_user.id), str(meraki_ws.id): str(create_user.id)}

    @pytest.mark.django_db
    def test_a_responsable_must_work_the_brand_in_that_unit(self, session_client, workspace, brands, meraki):
        meraki_ws, meraki_kfc, meraki_cm = meraki
        # Meraki's CM works the brand only in Meraki: not Responsable of Zil's unit
        wrong = {"responsibles": [{"workspace_id": str(workspace.id), "member_id": str(meraki_cm.id)}]}
        response = session_client.patch(self.url(workspace, brands), wrong, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert set(response.data) == {"responsibles"}

        # nor a unit that does not work the brand
        elsewhere = Workspace.objects.create(name="Otra", slug="otra", owner=meraki_cm)
        bad_unit = {"responsibles": [{"workspace_id": str(elsewhere.id), "member_id": None}]}
        assert session_client.patch(self.url(workspace, brands), bad_unit, format="json").status_code == 400

        # someone who leaves the brand in their unit stops showing as its Responsable
        ok = {"responsibles": [{"workspace_id": str(meraki_ws.id), "member_id": str(meraki_cm.id)}]}
        session_client.patch(self.url(workspace, brands), ok, format="json")
        ProjectMember.objects.filter(project=meraki_kfc, member=meraki_cm).update(is_active=False)
        units = self.get_ops(session_client, workspace, brands)["responsibles"]
        assert next(u for u in units if u["workspace_id"] == str(meraki_ws.id))["member_id"] is None

    @pytest.mark.django_db
    def test_a_unit_that_stopped_working_the_brand_has_no_responsable_row(
        self, session_client, workspace, brands, meraki
    ):
        _, meraki_kfc, _ = meraki
        Project.objects.filter(pk=meraki_kfc.pk).update(archived_at=timezone.now())
        units = self.get_ops(session_client, workspace, brands)["responsibles"]
        assert [u["workspace_id"] for u in units] == [str(workspace.id)]
