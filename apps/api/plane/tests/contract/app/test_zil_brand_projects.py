# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from datetime import timedelta
from unittest import mock

import pytest
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from plane.authentication.utils.zil_provisioning import provision_user_workspaces
from plane.db.models import (
    BotTypeEnum,
    Project,
    ProjectIdentifier,
    ProjectMember,
    State,
    User,
    WorkspaceMember,
    ZilBrandMember,
    ZilBrandProject,
    ZilBrandRoster,
)

KFC = "0123456789abcdef0123a001"
WENDYS = "0123456789abcdef0123a002"
SANTO_A = "0123456789abcdef0123a003"
SANTO_B = "0123456789abcdef0123a004"
EXTRA = ["0123456789abcdef0123b%03d" % n for n in range(10)]
ZIL_ENV = {"ZIL_SERVICE_SECRET": "secret"}


@pytest.fixture(autouse=True)
def service_key():
    with mock.patch.dict("os.environ", ZIL_ENV):
        yield


def push(workspace, brands, authoritative=True, computed_at=None, **extra):
    client = APIClient()
    client.credentials(HTTP_X_ZIL_SERVICE_KEY="secret")
    body = {"workspace_slug": workspace.slug, "brands": brands, "authoritative": authoritative, **extra}
    if computed_at is not None:
        body["computed_at"] = computed_at.isoformat()
    response = client.post("/api/zil/sync/brand-projects/", body, format="json")
    assert response.status_code == status.HTTP_200_OK, response.data
    return response.data


def brand(brand_id, name, members=None, status_="active", members_authoritative=True, color="#E2231A"):
    return {
        "brandId": brand_id,
        "name": name,
        "logo": f"https://zil.test/logos/{brand_id}.png",
        "color": color,
        "status": status_,
        "members": members or [],
        "membersAuthoritative": members_authoritative,
    }


def project_of(brand_id):
    return ZilBrandProject.objects.select_related("project").get(zil_brand_id=brand_id).project


def make_user(workspace, email, role=15, **fields):
    user = User.objects.create(email=email, username=email.split("@")[0], **fields)
    WorkspaceMember.objects.create(workspace=workspace, member=user, role=role)
    return user


def active_member_ids(project):
    return set(ProjectMember.objects.filter(project=project, is_active=True).values_list("member_id", flat=True))


def result_of(response, brand_id):
    return next(r for r in response["brands"] if r["brandId"] == brand_id)


@pytest.mark.contract
class TestBrandProjectCreation:
    @pytest.mark.django_db
    def test_a_brand_gets_a_private_project_with_its_color_identifier_and_states(self, workspace):
        response = push(workspace, [brand(KFC, "KFC")])

        project = project_of(KFC)
        assert response["created"] == 1
        assert result_of(response, KFC) == {
            "brandId": KFC,
            "projectId": str(project.id),
            "identifier": "KFC",
            "status": "created",
            "error": None,
        }
        assert project.network == 0 and project.name == "KFC" and project.identifier == "KFC"
        assert project.logo_props["icon"]["color"] == "#E2231A"
        assert ProjectIdentifier.objects.filter(project=project, name="KFC").exists()
        assert State.objects.filter(project=project).count() >= 5
        mapping = ZilBrandProject.objects.get(zil_brand_id=KFC)
        assert mapping.logo_url.endswith(f"{KFC}.png") and mapping.kind == "brand"

    @pytest.mark.django_db
    def test_brand_names_plane_rejects_are_project_names(self, workspace):
        push(workspace, [brand(WENDYS, "Wendy's"), brand(KFC, "Dean & Dennys")])
        assert project_of(WENDYS).name == "Wendy's"
        assert project_of(WENDYS).identifier == "WENDY"
        assert project_of(KFC).name == "Dean & Dennys"

    @pytest.mark.django_db
    def test_two_brands_with_one_name_get_a_suffix_from_the_brand_not_the_client(self, workspace):
        push(workspace, [brand(SANTO_A, "Santo"), brand(SANTO_B, "Santo")])
        names = {project_of(SANTO_A).name, project_of(SANTO_B).name}
        assert names == {"Santo", "Santo · A004"}
        assert project_of(SANTO_A).identifier != project_of(SANTO_B).identifier

    @pytest.mark.django_db
    def test_directors_and_agents_are_not_added(self, workspace, create_user):
        director = make_user(workspace, "director@zil.global", role=20)
        agent = User.objects.create(email="ada@agents.zil", username="ada", is_bot=True, bot_type=BotTypeEnum.ZIL_AGENT)
        WorkspaceMember.objects.create(workspace=workspace, member=agent, role=15)

        push(workspace, [brand(KFC, "KFC", members=[{"email": "director@zil.global", "role": "member"}])])

        members = active_member_ids(project_of(KFC))
        assert director.id not in members and agent.id not in members and create_user.id not in members

    @pytest.mark.django_db
    def test_an_existing_project_named_like_the_brand_is_adopted(self, workspace):
        studio = Project.objects.create(workspace=workspace, name="Rimón Café", identifier="RIMON", network=2)

        response = push(workspace, [brand(KFC, "Rimón Café")])

        assert response["adopted"] == 1 and response["created"] == 0
        assert project_of(KFC).id == studio.id
        studio.refresh_from_db()
        assert studio.network == 0 and studio.identifier == "RIMON"
        assert Project.objects.filter(workspace=workspace, name__iexact="Rimón Café").count() == 1


@pytest.mark.contract
class TestBrandRosterIdempotency:
    @pytest.mark.django_db
    def test_the_same_roster_twice_changes_nothing(self, workspace):
        ana = make_user(workspace, "ana@zil.global")
        roster = [brand(KFC, "KFC", members=[{"email": "ana@zil.global", "role": "member"}])]
        push(workspace, roster)
        membership = ProjectMember.objects.get(project=project_of(KFC), member=ana)
        before = (membership.updated_at, project_of(KFC).updated_at)

        again = push(workspace, roster)

        assert result_of(again, KFC)["status"] == "unchanged"
        assert again["created"] == again["members_added"] == again["members_removed"] == 0
        membership.refresh_from_db()
        assert (membership.updated_at, project_of(KFC).updated_at) == before
        assert ProjectMember.objects.filter(project=project_of(KFC), member=ana).count() == 1
        assert ZilBrandProject.objects.filter(zil_brand_id=KFC).count() == 1


@pytest.mark.contract
class TestBrandRosterOrder:
    @pytest.mark.django_db
    def test_an_older_roster_is_ignored(self, workspace):
        now = timezone.now()
        push(workspace, [brand(KFC, "KFC"), brand(WENDYS, "Wendy's")], computed_at=now)

        stale = push(workspace, [brand(KFC, "KFC")], computed_at=now - timedelta(minutes=5))

        assert stale["stale"] is True
        assert project_of(WENDYS).archived_at is None
        assert ZilBrandRoster.objects.get(workspace=workspace).synced_at == now

    @pytest.mark.django_db
    def test_an_older_roster_never_grants_access_back(self, workspace):
        ana = make_user(workspace, "ana@zil.global")
        now = timezone.now()
        team = [{"email": "ana@zil.global", "role": "member"}]
        push(workspace, [brand(KFC, "KFC", members=team)], computed_at=now - timedelta(minutes=10))
        push(workspace, [brand(KFC, "KFC", members=[])], computed_at=now)

        push(workspace, [brand(KFC, "KFC", members=team)], computed_at=now - timedelta(minutes=5))

        assert ana.id not in active_member_ids(project_of(KFC))

    @pytest.mark.django_db
    def test_a_roster_from_the_future_is_refused(self, workspace):
        client = APIClient()
        client.credentials(HTTP_X_ZIL_SERVICE_KEY="secret")
        response = client.post(
            "/api/zil/sync/brand-projects/",
            {
                "workspace_slug": workspace.slug,
                "brands": [brand(KFC, "KFC")],
                "authoritative": True,
                "computed_at": (timezone.now() + timedelta(hours=1)).isoformat(),
            },
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not ZilBrandProject.objects.exists()

    @pytest.mark.django_db
    def test_only_the_service_key_can_push(self, workspace):
        response = APIClient().post(
            "/api/zil/sync/brand-projects/", {"workspace_slug": workspace.slug, "brands": []}, format="json"
        )
        assert response.status_code in (401, 403)


@pytest.mark.contract
class TestEmptyRosterGuard:
    @pytest.mark.django_db
    def test_an_empty_authoritative_roster_archives_nothing(self, workspace):
        ana = make_user(workspace, "ana@zil.global")
        push(workspace, [brand(KFC, "KFC", members=[{"email": "ana@zil.global"}]), brand(WENDYS, "Wendy's")])

        response = push(workspace, [], computed_at=timezone.now())

        assert response["refused"] == "empty_roster" and response["archived"] == 0
        assert project_of(KFC).archived_at is None and project_of(WENDYS).archived_at is None
        assert ana.id in active_member_ids(project_of(KFC))

    @pytest.mark.django_db
    def test_a_roster_that_would_archive_most_brands_needs_force(self, workspace):
        everyone = [brand(b, f"Marca {n}") for n, b in enumerate(EXTRA)]
        push(workspace, everyone)

        truncated = push(workspace, everyone[:2])
        assert truncated["refused"] == "archive_fuse" and truncated["archived"] == 0
        assert not Project.objects.filter(zil_brand__isnull=False, archived_at__isnull=False).exists()

        forced = push(workspace, everyone[:2], force=True)
        assert forced["archived"] == 8

    @pytest.mark.django_db
    def test_empty_members_without_authority_revoke_nobody(self, workspace):
        ana = make_user(workspace, "ana@zil.global")
        push(workspace, [brand(KFC, "KFC", members=[{"email": "ana@zil.global"}])])

        push(workspace, [brand(KFC, "KFC", members=[], members_authoritative=False)])

        assert ana.id in active_member_ids(project_of(KFC))


@pytest.mark.contract
class TestBrandRename:
    @pytest.mark.django_db
    def test_renaming_the_brand_renames_the_project_but_not_its_identifier(self, workspace):
        push(workspace, [brand(KFC, "Kentucky")])
        identifier = project_of(KFC).identifier

        response = push(workspace, [brand(KFC, "KFC Argentina")])

        assert response["renamed"] == 1 and result_of(response, KFC)["status"] == "updated"
        assert project_of(KFC).name == "KFC Argentina" and project_of(KFC).identifier == identifier

    @pytest.mark.django_db
    def test_a_project_renamed_by_hand_keeps_its_name(self, workspace):
        push(workspace, [brand(KFC, "KFC")])
        project = project_of(KFC)
        project.name = "KFC (equipo)"
        project.save()

        push(workspace, [brand(KFC, "KFC Argentina")])

        assert project_of(KFC).name == "KFC (equipo)"


@pytest.mark.contract
class TestBrandArchive:
    @pytest.mark.django_db
    def test_an_archived_brand_archives_its_project_and_coming_back_restores_it(self, workspace):
        push(workspace, [brand(KFC, "KFC"), brand(WENDYS, "Wendy's")])

        archived = push(workspace, [brand(KFC, "KFC", status_="archived"), brand(WENDYS, "Wendy's")])
        assert archived["archived"] == 1 and result_of(archived, KFC)["status"] == "archived"
        assert project_of(KFC).archived_at is not None and project_of(KFC).deleted_at is None

        back = push(workspace, [brand(KFC, "KFC"), brand(WENDYS, "Wendy's")])
        assert back["restored"] == 1 and project_of(KFC).archived_at is None

    @pytest.mark.django_db
    def test_a_brand_leaving_an_authoritative_roster_is_archived_never_deleted(self, workspace):
        push(workspace, [brand(KFC, "KFC"), brand(WENDYS, "Wendy's")])

        partial = push(workspace, [brand(WENDYS, "Wendy's")], authoritative=False)
        assert project_of(KFC).archived_at is None and partial["archived"] == 0

        push(workspace, [brand(WENDYS, "Wendy's")])
        assert project_of(KFC).archived_at is not None
        assert Project.all_objects.filter(pk=project_of(KFC).pk, deleted_at__isnull=True).exists()


@pytest.mark.contract
class TestBrandMembers:
    @pytest.mark.django_db
    def test_the_team_becomes_the_members_and_leaving_it_revokes(self, workspace):
        ana = make_user(workspace, "ana@zil.global")
        beto = make_user(workspace, "beto@zil.global", role=5)
        team = [{"email": "ANA@zil.global", "role": "member"}, {"email": "beto@zil.global", "role": "guest"}]

        push(workspace, [brand(KFC, "KFC", members=team)])
        project = project_of(KFC)
        assert ProjectMember.objects.get(project=project, member=ana).role == 15
        assert ProjectMember.objects.get(project=project, member=beto).role == 5

        response = push(workspace, [brand(KFC, "KFC", members=team[:1])])
        assert response["members_removed"] == 1
        assert active_member_ids(project) == {ana.id}

    @pytest.mark.django_db
    def test_an_operator_never_gets_project_admin(self, workspace):
        ana = make_user(workspace, "ana@zil.global")
        push(workspace, [brand(KFC, "KFC")])
        ProjectMember.objects.create(project=project_of(KFC), member=ana, role=20)

        push(workspace, [brand(KFC, "KFC", members=[{"email": "ana@zil.global"}])])

        assert ProjectMember.objects.get(project=project_of(KFC), member=ana).role == 15

    @pytest.mark.django_db
    def test_a_director_who_joined_is_left_alone(self, workspace):
        director = make_user(workspace, "director@zil.global", role=20)
        push(workspace, [brand(KFC, "KFC")])
        ProjectMember.objects.create(project=project_of(KFC), member=director, role=20)

        push(workspace, [brand(KFC, "KFC", members=[])])

        assert director.id in active_member_ids(project_of(KFC))

    @pytest.mark.django_db
    def test_someone_who_never_signed_in_joins_on_their_first_sign_in(self, workspace):
        response = push(workspace, [brand(KFC, "KFC", members=[{"email": "nueva@zil.global"}])])
        assert response["members_pending"] == 1
        assert ZilBrandMember.objects.filter(email="nueva@zil.global").exists()

        user = User.objects.create(email="nueva@zil.global", username="nueva")
        provision_user_workspaces(user, [{"slug": workspace.slug, "name": workspace.name, "role": "operativo"}])

        assert user.id in active_member_ids(project_of(KFC))

    @pytest.mark.django_db
    def test_one_brand_failing_does_not_stop_the_revocations_of_the_others(self, workspace):
        ana = make_user(workspace, "ana@zil.global")
        team = [{"email": "ana@zil.global"}]
        push(workspace, [brand(KFC, "KFC", members=team), brand(WENDYS, "Wendy's", members=team)])

        real_apply = __import__("plane.utils.zil_brand_projects", fromlist=["x"])._apply_brand

        def fail_for_kfc(workspace_, brand_, *args, **kwargs):
            if brand_["id"] == KFC:
                raise RuntimeError("logo inválido")
            return real_apply(workspace_, brand_, *args, **kwargs)

        with mock.patch("plane.utils.zil_brand_projects._apply_brand", side_effect=fail_for_kfc):
            response = push(workspace, [brand(KFC, "KFC", members=team), brand(WENDYS, "Wendy's", members=[])])

        assert result_of(response, KFC)["status"] == "error" and "logo" in result_of(response, KFC)["error"]
        assert result_of(response, WENDYS)["status"] == "updated"
        assert ana.id not in active_member_ids(project_of(WENDYS))
        assert project_of(KFC).archived_at is None


@pytest.mark.contract
class TestBrandRosterDryRun:
    @pytest.mark.django_db
    def test_a_dry_run_reports_and_keeps_nothing(self, workspace):
        make_user(workspace, "ana@zil.global")
        response = push(workspace, [brand(KFC, "KFC", members=[{"email": "ana@zil.global"}])], dry_run=True)

        assert response["dry_run"] is True and response["created"] == 1 and response["members_added"] == 1
        assert not ZilBrandProject.objects.exists() and not ZilBrandRoster.objects.exists()
        assert not Project.objects.filter(name="KFC").exists()


@pytest.mark.contract
class TestClientFoldersSuperseded:
    @pytest.mark.django_db
    def test_the_old_client_folders_push_stops_once_brands_arrive(self, workspace):
        push(workspace, [brand(KFC, "KFC")])
        client = APIClient()
        client.credentials(HTTP_X_ZIL_SERVICE_KEY="secret")
        response = client.post(
            "/api/zil/sync/client-folders/",
            {"workspace_slug": workspace.slug, "clients": [{"id": KFC, "alias": "Grupo"}], "authoritative": True},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK and response.data["superseded"] is True


@pytest.mark.contract
class TestArchivedBrandsWithoutProject:
    @pytest.mark.django_db
    def test_an_archived_brand_never_seen_gets_no_project(self, workspace):
        response = push(workspace, [brand(KFC, "KFC"), brand(WENDYS, "Wendys", status_="archived")])

        assert response["created"] == 1 and response["skipped"] == 1 and response["refused"] is None
        assert result_of(response, WENDYS) == {
            "brandId": WENDYS,
            "projectId": None,
            "identifier": None,
            "status": "skipped",
            "error": None,
        }
        assert not ZilBrandProject.objects.filter(zil_brand_id=WENDYS).exists()

    @pytest.mark.django_db
    def test_many_archived_brands_on_a_first_run_neither_create_nor_trip_the_fuse(self, workspace):
        roster = [brand(KFC, "KFC")] + [brand(b, f"Vieja {n}", status_="archived") for n, b in enumerate(EXTRA)]
        response = push(workspace, roster)
        assert response["created"] == 1 and response["skipped"] == 10 and response["refused"] is None
        assert ZilBrandProject.objects.count() == 1


@pytest.mark.contract
class TestAdoptionCleanup:
    @pytest.mark.django_db
    def test_adopting_drops_pending_invitations_and_unrequested_agents(self, workspace):
        from plane.db.models import ProjectMemberInvite

        studio = Project.objects.create(workspace=workspace, name="Rimon Cafe", identifier="RIMON")
        agent = User.objects.create(email="ada@agents.zil", username="ada", is_bot=True, bot_type=BotTypeEnum.ZIL_AGENT)
        WorkspaceMember.objects.create(workspace=workspace, member=agent, role=15)
        ProjectMember.objects.create(project=studio, member=agent, role=15)
        ProjectMemberInvite.objects.create(project=studio, email="x@zil.global", token="t", role=15)

        push(workspace, [brand(KFC, "Rimon Cafe")])

        assert not ProjectMemberInvite.objects.filter(project=studio).exists()
        assert agent.id not in active_member_ids(studio)


@pytest.mark.contract
class TestUserBrandProjectsFastPath:
    def sync_user(self, body):
        client = APIClient()
        client.credentials(HTTP_X_ZIL_SERVICE_KEY="secret")
        response = client.post("/api/zil/sync/user/", body, format="json")
        assert response.status_code == status.HTTP_200_OK, response.data
        return response.data

    @pytest.mark.django_db
    def test_a_revoked_brand_is_left_at_once_and_the_rest_kept(self, workspace):
        ana = make_user(workspace, "ana@zil.global")
        team = [{"email": "ana@zil.global"}]
        push(workspace, [brand(KFC, "KFC", members=team), brand(WENDYS, "Wendys", members=team)])

        body = self.sync_user(
            {
                "email": "ana@zil.global",
                "brand_projects": [{"brandId": KFC, "role": "member", "workspace_slug": workspace.slug}],
                "brand_projects_authoritative": True,
            }
        )

        assert body["brand_projects"] == {"added": 0, "removed": 1, "pending": 0}
        assert ana.id in active_member_ids(project_of(KFC))
        assert ana.id not in active_member_ids(project_of(WENDYS))
        assert not ZilBrandMember.objects.filter(email="ana@zil.global", brand_project__zil_brand_id=WENDYS).exists()
        # a brands-only call leaves the workspaces alone
        assert WorkspaceMember.objects.get(workspace=workspace, member=ana).is_active

    @pytest.mark.django_db
    def test_without_authority_it_only_adds(self, workspace):
        ana = make_user(workspace, "ana@zil.global")
        push(workspace, [brand(KFC, "KFC", members=[{"email": "ana@zil.global"}]), brand(WENDYS, "Wendys")])

        body = self.sync_user({"email": "ana@zil.global", "brand_projects": [{"brandId": WENDYS}]})

        assert body["brand_projects"]["added"] == 1
        assert ana.id in active_member_ids(project_of(KFC)) and ana.id in active_member_ids(project_of(WENDYS))

    @pytest.mark.django_db
    def test_someone_who_never_signed_in_loses_the_brand_on_record(self, workspace):
        push(workspace, [brand(KFC, "KFC", members=[{"email": "nueva@zil.global"}])])

        body = self.sync_user({"email": "nueva@zil.global", "brand_projects": [], "brand_projects_authoritative": True})

        assert body["status"] == "skipped"
        assert not ZilBrandMember.objects.filter(email="nueva@zil.global").exists()


@pytest.mark.contract
class TestRefusedRosterChangesNoAccess:
    @pytest.mark.django_db
    def test_a_roster_the_fuse_refuses_revokes_nobody(self, workspace):
        # a broken roster: 2 of 10 brands, and the 2 with an empty authoritative team. Applied before
        # the fuse was decided, it emptied those projects and then refused only the archiving
        ana = make_user(workspace, "ana@zil.global")
        team = [{"email": "ana@zil.global", "role": "member"}]
        everyone = [brand(b, f"Marca {n}", members=team) for n, b in enumerate(EXTRA)]
        push(workspace, everyone)

        broken = [brand(b, f"Marca {n}", members=[]) for n, b in enumerate(EXTRA[:2])]
        response = push(workspace, broken)

        assert response["refused"] == "archive_fuse"
        assert response["members_removed"] == 0 and response["archived"] == 0
        for brand_id in EXTRA:
            assert ana.id in active_member_ids(project_of(brand_id))
            assert ZilBrandMember.objects.filter(brand_project__zil_brand_id=brand_id, email=ana.email).exists()

    @pytest.mark.django_db
    def test_with_force_the_same_roster_applies_in_full(self, workspace):
        ana = make_user(workspace, "ana@zil.global")
        team = [{"email": "ana@zil.global", "role": "member"}]
        push(workspace, [brand(b, f"Marca {n}", members=team) for n, b in enumerate(EXTRA)])

        response = push(workspace, [brand(b, f"Marca {n}", members=[]) for n, b in enumerate(EXTRA[:2])], force=True)

        assert response["refused"] is None and response["archived"] == 8
        assert ana.id not in active_member_ids(project_of(EXTRA[0]))
