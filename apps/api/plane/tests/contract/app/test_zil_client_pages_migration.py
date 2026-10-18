# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import json
from io import StringIO

import pytest
from django.core.management import call_command

from plane.db.models import (
    FileAsset,
    Label,
    Page,
    PageLabel,
    PageZilClientLink,
    Project,
    ProjectMember,
    ProjectPage,
    User,
    UserFavorite,
    WorkspaceMember,
    ZilBrandProject,
    ZilClientsRoot,
)
from plane.utils.zil_brand_projects import apply_brand_roster
from plane.utils.zil_client_folders import apply_client_folders
from plane.utils.zil_page_move import migrate_client_pages

RIMON = "0123456789abcdef0000c001"  # one brand
DEGASA = "0123456789abcdef0000c002"  # several brands
NUEVO = "0123456789abcdef0000c003"  # not in the map
RIMON_BRAND = "0123456789abcdef0000b001"
KFC = "0123456789abcdef0000b002"
WENDYS = "0123456789abcdef0000b003"

CLIENT_BRANDS = {
    RIMON: [{"brandId": RIMON_BRAND, "name": "Rimón Café", "status": "active"}],
    DEGASA: [
        {"brandId": KFC, "name": "KFC", "status": "active"},
        {"brandId": WENDYS, "name": "Wendy's", "status": "active"},
    ],
}


def client(client_id, alias):
    return {"id": client_id, "alias": alias, "companyName": f"{alias} SA", "lifecycleStatus": "active"}


def page_in(project, name, parent, owner, **fields):
    page = Page.objects.create(workspace_id=project.workspace_id, name=name, parent=parent, owned_by=owner, **fields)
    ProjectPage.objects.create(workspace_id=project.workspace_id, project=project, page=page)
    return page


def live_projects(page):
    return set(ProjectPage.objects.filter(page=page, deleted_at__isnull=True).values_list("project_id", flat=True))


@pytest.fixture
def setup(workspace, create_user):
    main = Project.objects.create(workspace=workspace, name=workspace.name, identifier="MAIN")
    ProjectMember.objects.create(project=main, member=create_user, role=20)
    apply_client_folders(
        workspace.id, [client(RIMON, "Rimon"), client(DEGASA, "Grupo Degasa"), client(NUEVO, "Nuevo")], True
    )
    ana = User.objects.create(email="ana@zil.global", username="ana")
    WorkspaceMember.objects.create(workspace=workspace, member=ana, role=15)
    apply_brand_roster(
        workspace.id,
        [
            {
                "brandId": RIMON_BRAND,
                "name": "Rimón Café",
                "members": [{"email": ana.email}],
                "membersAuthoritative": True,
            },
            {"brandId": KFC, "name": "KFC"},
            {"brandId": WENDYS, "name": "Wendy's"},
        ],
        authoritative=True,
    )
    folder = PageZilClientLink.objects.get(zil_client_id=RIMON).page
    brief = page_in(main, "Brief", folder, create_user)
    private = page_in(main, "Notas mías", brief, create_user, access=Page.PRIVATE_ACCESS)
    label = Label.objects.create(project=main, workspace=workspace, name="Branding", color="#f00")
    PageLabel.objects.create(page=brief, label=label, workspace=workspace)
    asset = FileAsset.objects.create(
        workspace=workspace, project=main, page=brief, asset="a.png", attributes={}, entity_type="PAGE_DESCRIPTION"
    )
    favorite = UserFavorite.objects.create(
        workspace=workspace, project=main, user=ana, entity_type="page", entity_identifier=brief.id
    )
    degasa_page = page_in(
        main, "Mix KFC y Wendy's", PageZilClientLink.objects.get(zil_client_id=DEGASA).page, create_user
    )
    stray = page_in(main, "Algo suelto", ZilClientsRoot.objects.get().page, create_user)
    return {
        "main": main,
        "folder": folder,
        "brief": brief,
        "private": private,
        "asset": asset,
        "favorite": favorite,
        "degasa_page": degasa_page,
        "stray": stray,
        "rimon": ZilBrandProject.objects.get(zil_brand_id=RIMON_BRAND).project,
    }


@pytest.mark.contract
class TestClientPagesMigration:
    @pytest.mark.django_db
    def test_a_dry_run_reports_and_changes_nothing(self, workspace, setup):
        report = migrate_client_pages(CLIENT_BRANDS)

        ws = report["workspaces"][0]
        assert report["applied"] is False
        assert ws["totals"]["folders"] == 2 and ws["totals"]["to_migration"] == 1 and ws["totals"]["skipped"] == 1
        assert {s["reason"] for s in ws["skipped"]} == {"client_not_in_map"}
        assert live_projects(setup["brief"]) == {setup["main"].id}
        assert ZilClientsRoot.objects.exists() and PageZilClientLink.objects.count() == 3
        assert not ZilBrandProject.objects.filter(kind="migration").exists()

    @pytest.mark.django_db
    def test_a_single_brand_client_folder_moves_to_its_brand_with_what_hangs_from_it(self, workspace, setup):
        migrate_client_pages(CLIENT_BRANDS, apply=True)

        rimon = setup["rimon"]
        folder = Page.objects.get(pk=setup["folder"].pk)
        assert folder.parent_id is None and folder.name == "Documentos"
        for page in (folder, setup["brief"], setup["private"]):
            assert live_projects(page) == {rimon.id}
            assert Page.objects.get(pk=page.pk).moved_to_project == rimon.id
        setup["asset"].refresh_from_db()
        assert setup["asset"].project_id == rimon.id
        moved_label = PageLabel.objects.select_related("label").get(page=setup["brief"]).label
        assert moved_label.project_id == rimon.id and moved_label.name == "Branding"
        setup["favorite"].refresh_from_db()
        assert setup["favorite"].project_id == rimon.id
        assert not PageZilClientLink.objects.filter(zil_client_id=RIMON).exists()

    @pytest.mark.django_db
    def test_a_client_with_several_brands_goes_to_a_private_migration_project_for_directors(
        self, workspace, setup, create_user
    ):
        report = migrate_client_pages(CLIENT_BRANDS, apply=True)

        migration = ZilBrandProject.objects.get(kind="migration").project
        assert migration.network == 0 and migration.name == "Migración"
        assert set(
            ProjectMember.objects.filter(project=migration, is_active=True).values_list("member_id", flat=True)
        ) == {create_user.id}
        assert live_projects(setup["degasa_page"]) == {migration.id}
        assert report["workspaces"][0]["migration_project"] == "Migración"

    @pytest.mark.django_db
    def test_the_clientes_folder_disappears_and_what_else_was_in_it_stays(self, workspace, setup):
        report = migrate_client_pages(CLIENT_BRANDS, apply=True)

        assert not ZilClientsRoot.objects.exists()
        assert not Page.objects.filter(name="Clientes", kind=Page.FOLDER_KIND).exists()
        stray = Page.objects.get(pk=setup["stray"].pk)
        assert stray.parent_id is None and live_projects(stray) == {setup["main"].id}
        assert "Algo suelto" in report["workspaces"][0]["roots"][0]["lifted_to_top"]

    @pytest.mark.django_db
    def test_private_pages_whose_owner_is_not_in_the_brand_are_listed(self, workspace, setup):
        report = migrate_client_pages(CLIENT_BRANDS, apply=True)
        moved = next(m for m in report["workspaces"][0]["moved"] if m["client_id"] == RIMON)
        assert [p["name"] for p in moved["unreachable_private"]] == ["Notas mías"]

    @pytest.mark.django_db
    def test_work_items_do_not_move(self, workspace, setup):
        from plane.db.models import Issue

        issue = Issue.objects.create(name="Pieza", project=setup["main"], workspace=workspace)
        migrate_client_pages(CLIENT_BRANDS, apply=True)
        issue.refresh_from_db()
        assert issue.project_id == setup["main"].id

    @pytest.mark.django_db
    def test_the_command_is_a_dry_run_by_default(self, workspace, setup, tmp_path):
        path = tmp_path / "map.json"
        path.write_text(json.dumps({"generatedAt": "2026-10-18T00:00:00Z", "clients": CLIENT_BRANDS}))
        out = StringIO()
        call_command("zil_migrate_client_pages", "--map", str(path), stdout=out)
        assert "DRY RUN" in out.getvalue()
        assert PageZilClientLink.objects.count() == 3


@pytest.mark.contract
class TestMovedPageLinks:
    @pytest.mark.django_db
    def test_an_old_link_to_a_moved_page_points_to_its_new_project(self, session_client, workspace, setup, create_user):
        from unittest import mock

        migrate_client_pages(CLIENT_BRANDS, apply=True)
        rimon = setup["rimon"]
        brief = setup["brief"]
        old = f"/api/workspaces/{workspace.slug}/projects/{setup['main'].id}/pages/{brief.id}/"

        # not on the brand's team: the old link says nothing about where the page went
        response = session_client.get(old)
        assert response.status_code == 404 and "moved_to_project" not in response.data

        ProjectMember.objects.create(project=rimon, member=create_user, role=20)
        with mock.patch("plane.app.views.page.base.recent_visited_task.delay"):
            response = session_client.get(old)
        assert response.status_code == 404 and response.data["moved_to_project"] == str(rimon.id)
