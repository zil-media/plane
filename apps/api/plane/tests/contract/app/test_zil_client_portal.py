# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from datetime import timedelta
from unittest import mock

import pytest
from django.core.management import call_command
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from plane.authentication.utils.redirection_path import get_redirection_path
from plane.db.models import (
    FileAsset,
    Issue,
    IssueAssignee,
    IssueComment,
    IssueLabel,
    IssueView,
    Label,
    Notification,
    Page,
    ProjectPage,
    State,
    User,
    Workspace,
    WorkspaceMember,
    ZilBrandClient,
    ZilBrandOps,
    ZilBrandProject,
    ZilClientPortal,
)
from plane.utils.zil_client_portal import (
    CLIENT_FOLDER,
    CONTENT_LABELS,
    CONTENT_STATES,
    REVIEW_STATE,
    VISIBLE_LABEL,
    dispatch_portal_events,
)

KFC = "0123456789abcdef0123c001"
WENDYS = "0123456789abcdef0123c002"
EMAIL_TASK = "plane.bgtasks.agent_pipeline_task.send_support_email_task.delay"


@pytest.fixture(autouse=True)
def service_key():
    with mock.patch.dict("os.environ", {"ZIL_SERVICE_SECRET": "secret"}):
        yield


@pytest.fixture
def emails():
    with mock.patch(EMAIL_TASK) as task:
        yield task


def push(workspace, brands):
    client = APIClient()
    client.credentials(HTTP_X_ZIL_SERVICE_KEY="secret")
    body = {"workspace_slug": workspace.slug, "brands": brands, "authoritative": True}
    response = client.post("/api/zil/sync/brand-projects/", body, format="json")
    assert response.status_code == status.HTTP_200_OK, response.data
    return response.data


def brand(brand_id, name, clients=(), status_="active", team=()):
    members = [{"email": e} for e in team] + [{"email": e, "role": "client"} for e in clients]
    return {
        "brandId": brand_id,
        "name": name,
        "logo": f"https://zil.test/logos/{brand_id}.png",
        "color": "#E2231A",
        "status": status_,
        "members": members,
        "membersAuthoritative": True,
    }


def mapping_of(brand_id):
    return ZilBrandProject.objects.select_related("project").get(zil_brand_id=brand_id)


def as_user(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def turn_on(brand_id):
    portal = ZilClientPortal.objects.get(project=mapping_of(brand_id).project)
    portal.enabled = True
    portal.save()
    return portal


def item(project, name, visible=True, state_name="Diseño", target_date=None, **fields):
    state = State.objects.get(project=project, name=state_name)
    issue = Issue.objects.create(
        name=name,
        project=project,
        workspace_id=project.workspace_id,
        state=state,
        target_date=target_date,
        description_html=f"<p>{name} copy</p>",
        **fields,
    )
    if visible:
        IssueLabel.objects.create(
            issue=issue,
            label=Label.objects.get(project=project, name=VISIBLE_LABEL),
            project=project,
            workspace_id=project.workspace_id,
        )
    return issue


@pytest.fixture
def kfc(workspace, emails):
    """KFC with one client (cliente@kfc.test) and its portal on."""
    push(workspace, [brand(KFC, "KFC", clients=["cliente@kfc.test"])])
    turn_on(KFC)
    return mapping_of(KFC)


@pytest.fixture
def cliente(kfc):
    user = User.objects.get(email="cliente@kfc.test")
    user.last_login_time = timezone.now()
    user.is_password_autoset = False
    user.save()
    return user


@pytest.mark.contract
class TestSeed:
    @pytest.mark.django_db
    def test_a_new_brand_gets_its_content_calendar_and_a_client_folder_with_the_portal_off(self, workspace, emails):
        push(workspace, [brand(KFC, "KFC")])
        project = mapping_of(KFC).project

        names = set(State.objects.filter(project=project).values_list("name", flat=True))
        assert {s["name"] for s in CONTENT_STATES} <= names
        assert State.objects.get(project=project, name="Publicado").group == "completed"
        labels = set(Label.objects.filter(project=project).values_list("name", flat=True))
        assert {label["name"] for label in CONTENT_LABELS} <= labels
        view = IssueView.objects.get(project=project, name="Calendario de contenidos")
        assert view.display_filters["layout"] == "calendar"
        project.refresh_from_db()
        assert project.issue_views_view
        portal = ZilClientPortal.objects.get(project=project)
        assert not portal.enabled
        assert portal.pages_folder.name == CLIENT_FOLDER and portal.pages_folder.kind == Page.FOLDER_KIND
        assert ProjectPage.objects.filter(project=project, page=portal.pages_folder).exists()

    @pytest.mark.django_db
    def test_seeding_again_or_the_backfill_adds_nothing_and_keeps_renamed_things(self, workspace, emails):
        push(workspace, [brand(KFC, "KFC")])
        project = mapping_of(KFC).project
        State.objects.filter(project=project, name="Idea").update(color="#000000")
        counts = (State.objects.filter(project=project).count(), Label.objects.filter(project=project).count())

        push(workspace, [brand(KFC, "KFC")])
        call_command("zil_seed_brand_content")

        assert (State.objects.filter(project=project).count(), Label.objects.filter(project=project).count()) == counts
        assert State.objects.get(project=project, name="Idea").color == "#000000"
        assert IssueView.objects.filter(project=project, name="Calendario de contenidos").count() == 1
        assert Page.objects.filter(project_pages__project=project, name=CLIENT_FOLDER).count() == 1

    @pytest.mark.django_db
    def test_a_brand_made_before_the_portal_gets_it_on_its_next_roster(self, workspace, emails):
        push(workspace, [brand(KFC, "KFC")])
        project = mapping_of(KFC).project
        ZilClientPortal.objects.filter(project=project).delete(soft=False)

        push(workspace, [brand(KFC, "KFC")])

        assert ZilClientPortal.objects.filter(project=project).exists()


@pytest.mark.contract
class TestAccess:
    @pytest.mark.django_db
    def test_the_client_sees_their_brand_and_mis_marcas_lists_it(self, kfc, cliente):
        client = as_user(cliente)

        brands = client.get("/api/public/portal/").json()["brands"]
        header = client.get(f"/api/public/portal/{kfc.project_id}/").json()

        assert brands == [
            {
                "id": str(kfc.project_id),
                "name": "KFC",
                "logo_url": f"https://zil.test/logos/{KFC}.png",
                "color": "#E2231A",
                "paused": False,
            }
        ]
        assert header["name"] == "KFC" and header["preview"] is False

    @pytest.mark.django_db
    def test_nobody_else_gets_in_and_the_answer_never_says_the_portal_exists(self, workspace, kfc, cliente, emails):
        push(workspace, [brand(KFC, "KFC", clients=["cliente@kfc.test"]), brand(WENDYS, "Wendys", ["w@w.test"])])
        turn_on(WENDYS)
        wendys_client = User.objects.get(email="w@w.test")
        stranger = User.objects.create(email="stranger@x.test", username="stranger")
        url = f"/api/public/portal/{kfc.project_id}/posts/"

        assert as_user(wendys_client).get(url).status_code == status.HTTP_404_NOT_FOUND
        assert as_user(stranger).get(url).status_code == status.HTTP_404_NOT_FOUND
        assert APIClient().get(url).status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)
        assert as_user(cliente).get(url).status_code == status.HTTP_200_OK

    @pytest.mark.django_db
    def test_a_portal_that_is_off_is_not_found(self, kfc, cliente):
        ZilClientPortal.objects.filter(project_id=kfc.project_id).update(enabled=False)

        assert as_user(cliente).get(f"/api/public/portal/{kfc.project_id}/").status_code == 404
        assert as_user(cliente).get("/api/public/portal/").json()["brands"] == []

    @pytest.mark.django_db
    def test_a_suspended_brand_pauses_its_clients_and_coming_back_resumes_them(self, workspace, kfc, cliente):
        push(workspace, [brand(KFC, "KFC", clients=["cliente@kfc.test"], status_="archived")])

        paused = as_user(cliente).get(f"/api/public/portal/{kfc.project_id}/posts/")
        assert paused.status_code == status.HTTP_403_FORBIDDEN and paused.json()["paused"] is True
        assert as_user(cliente).get("/api/public/portal/").json()["brands"][0]["paused"] is True

        push(workspace, [brand(KFC, "KFC", clients=["cliente@kfc.test"])])
        assert as_user(cliente).get(f"/api/public/portal/{kfc.project_id}/posts/").status_code == 200

    @pytest.mark.django_db
    def test_a_team_member_previews_the_portal_but_answers_from_ops(self, kfc, create_user):
        issue = item(kfc.project, "Reel lanzamiento")
        client = as_user(create_user)

        assert client.get(f"/api/public/portal/{kfc.project_id}/").json()["preview"] is True
        response = client.post(
            f"/api/public/portal/{kfc.project_id}/posts/{issue.id}/comments/", {"text": "hola"}, format="json"
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.django_db
    def test_a_deactivated_client_loses_the_portal(self, kfc, cliente):
        cliente.is_active = False
        cliente.save()

        assert as_user(cliente).get(f"/api/public/portal/{kfc.project_id}/").status_code in (401, 403, 404)


@pytest.mark.contract
class TestPosts:
    @pytest.mark.django_db
    def test_only_items_marked_for_the_client_show_and_only_whitelisted_fields(self, kfc, cliente, create_user):
        project = kfc.project
        today = timezone.now().date()
        shown = item(project, "Reel lanzamiento", target_date=today, priority="urgent")
        item(project, "Interno", visible=False, target_date=today)
        IssueLabel.objects.create(
            issue=shown,
            label=Label.objects.get(project=project, name="Instagram"),
            project=project,
            workspace_id=project.workspace_id,
        )
        IssueAssignee.objects.create(
            issue=shown, assignee=create_user, project=project, workspace_id=project.workspace_id
        )

        body = (
            as_user(cliente)
            .get(f"/api/public/portal/{project.id}/posts/", {"start": today.isoformat(), "end": today.isoformat()})
            .json()
        )

        assert [p["name"] for p in body["posts"]] == ["Reel lanzamiento"]
        post = body["posts"][0]
        assert set(post) == {"id", "name", "publish_date", "status", "network", "labels", "thumbnail"}
        assert post["network"] == "Instagram" and post["status"] == "En preparación"
        assert [label["name"] for label in post["labels"]] == ["Instagram"]
        assert body["to_review"] == []

    @pytest.mark.django_db
    def test_the_review_strip_and_the_four_plain_statuses(self, kfc, cliente):
        project = kfc.project
        review = item(project, "Carrusel", state_name=REVIEW_STATE)
        item(project, "Programada", state_name="Programado", target_date=timezone.now().date())
        item(project, "Salió", state_name="Publicado", target_date=timezone.now().date())

        body = as_user(cliente).get(f"/api/public/portal/{project.id}/posts/").json()

        assert [p["id"] for p in body["to_review"]] == [str(review.id)]
        assert body["to_review"][0]["status"] == "Para revisar"
        assert sorted(p["status"] for p in body["posts"]) == ["Programada", "Publicada"]

    @pytest.mark.django_db
    def test_a_post_detail_has_the_copy_and_media_and_a_hidden_one_is_not_found(self, kfc, cliente):
        project = kfc.project
        shown = item(project, "Reel")
        hidden = item(project, "Interno", visible=False)
        asset = FileAsset.objects.create(
            asset="kfc/reel.jpg",
            attributes={"name": "reel.jpg", "type": "image/jpeg", "size": 10},
            entity_type=FileAsset.EntityTypeContext.ISSUE_ATTACHMENT,
            issue=shown,
            project=project,
            workspace_id=project.workspace_id,
            is_uploaded=True,
        )

        detail = as_user(cliente).get(f"/api/public/portal/{project.id}/posts/{shown.id}/").json()

        assert detail["description_html"] == "<p>Reel copy</p>"
        assert detail["media"][0]["url"] == f"/api/public/portal/{project.id}/assets/{asset.id}/"
        assert detail["thumbnail"]["id"] == str(asset.id)
        assert "assignees" not in detail and "priority" not in detail
        assert as_user(cliente).get(f"/api/public/portal/{project.id}/posts/{hidden.id}/").status_code == 404

    @pytest.mark.django_db
    def test_files_open_only_for_what_the_client_sees(self, kfc, cliente):
        project = kfc.project
        hidden = item(project, "Interno", visible=False)
        shown = item(project, "Reel")

        def asset_of(issue):
            return FileAsset.objects.create(
                asset=f"kfc/{issue.id}.jpg",
                attributes={"name": "x.jpg", "type": "image/jpeg"},
                entity_type=FileAsset.EntityTypeContext.ISSUE_ATTACHMENT,
                issue=issue,
                project=project,
                workspace_id=project.workspace_id,
                is_uploaded=True,
            )

        hidden_asset, shown_asset = asset_of(hidden), asset_of(shown)
        with mock.patch(
            "plane.space.views.zil_portal.S3Storage.generate_presigned_url", return_value="https://s3.test/x"
        ):
            ok = as_user(cliente).get(f"/api/public/portal/{project.id}/assets/{shown_asset.id}/")
            nope = as_user(cliente).get(f"/api/public/portal/{project.id}/assets/{hidden_asset.id}/")

        assert ok.status_code == 302 and ok["Location"] == "https://s3.test/x"
        assert nope.status_code == 404


@pytest.mark.contract
class TestComments:
    @pytest.mark.django_db
    def test_the_client_reads_only_external_comments_and_writes_external_ones(self, kfc, cliente, create_user):
        project = kfc.project
        issue = item(project, "Reel")
        IssueComment.objects.create(
            issue=issue, project=project, comment_html="<p>interno</p>", actor=create_user, access="INTERNAL"
        )
        IssueComment.objects.create(
            issue=issue, project=project, comment_html="<p>¿te gusta?</p>", actor=create_user, access="EXTERNAL"
        )
        url = f"/api/public/portal/{project.id}/posts/{issue.id}/comments/"

        with mock.patch("plane.space.views.zil_portal.issue_activity.delay") as activity:
            created = as_user(cliente).post(url, {"text": "Me encanta\n<b>sí</b>"}, format="json")
        comments = as_user(cliente).get(url).json()["comments"]

        assert created.status_code == status.HTTP_201_CREATED
        activity.assert_called_once()
        stored = IssueComment.objects.get(pk=created.json()["id"])
        assert stored.access == "EXTERNAL" and stored.actor_id == cliente.id
        assert stored.comment_html == "<p>Me encanta</p><p>&lt;b&gt;sí&lt;/b&gt;</p>"
        assert [c["html"] for c in comments] == ["<p>¿te gusta?</p>", stored.comment_html]
        assert comments[0]["is_team"] and comments[1]["is_mine"]

    @pytest.mark.django_db
    def test_a_client_comment_notifies_the_cms_in_ops_and_by_email(self, kfc, cliente, create_user, emails):
        project = kfc.project
        ops = ZilBrandOps.objects.create(zil_brand_id=KFC)
        ops.community_managers.add(create_user)
        issue = item(project, "Reel")
        comment = IssueComment.objects.create(
            issue=issue, project=project, comment_html="<p>Cambiar el color</p>", actor=cliente, access="EXTERNAL"
        )
        emails.reset_mock()

        dispatch_portal_events(
            "comment.activity.created",
            issue.id,
            cliente.id,
            [mock.Mock(field="comment", issue_comment_id=comment.id)],
        )

        notice = Notification.objects.get(receiver=create_user)
        assert notice.entity_identifier == issue.id and "(cliente)" in notice.title
        assert emails.call_args.args[0] == [create_user.email]

    @pytest.mark.django_db
    def test_the_teams_external_answer_and_a_post_to_review_email_the_client(self, kfc, cliente, create_user, emails):
        project = kfc.project
        issue = item(project, "Reel", state_name=REVIEW_STATE)
        answer = IssueComment.objects.create(
            issue=issue, project=project, comment_html="<p>Listo</p>", actor=create_user, access="EXTERNAL"
        )
        internal = IssueComment.objects.create(
            issue=issue, project=project, comment_html="<p>nota</p>", actor=create_user, access="INTERNAL"
        )
        emails.reset_mock()

        dispatch_portal_events(
            "comment.activity.created",
            issue.id,
            create_user.id,
            [mock.Mock(field="comment", issue_comment_id=internal.id)],
        )
        assert not emails.called
        dispatch_portal_events(
            "comment.activity.created",
            issue.id,
            create_user.id,
            [mock.Mock(field="comment", issue_comment_id=answer.id)],
        )
        dispatch_portal_events(
            "issue.activity.updated", issue.id, create_user.id, [mock.Mock(field="state", new_value=REVIEW_STATE)]
        )

        recipients = [call.args[0] for call in emails.call_args_list]
        assert recipients == [["cliente@kfc.test"], ["cliente@kfc.test"]]
        assert f"?post={issue.id}" in emails.call_args.args[5]

    @pytest.mark.django_db
    def test_a_hidden_item_never_emails_the_client(self, kfc, cliente, create_user, emails):
        issue = item(kfc.project, "Interno", visible=False, state_name=REVIEW_STATE)
        emails.reset_mock()

        dispatch_portal_events(
            "issue.activity.updated", issue.id, create_user.id, [mock.Mock(field="state", new_value=REVIEW_STATE)]
        )

        assert not emails.called


@pytest.mark.contract
class TestDocuments:
    @pytest.mark.django_db
    def test_only_pages_inside_the_client_folder_are_listed_and_readable(self, kfc, cliente, create_user):
        project = kfc.project
        folder = ZilClientPortal.objects.get(project=project).pages_folder

        def page(name, parent=None, kind=Page.PAGE_KIND):
            created = Page.objects.create(
                name=name,
                parent=parent,
                kind=kind,
                workspace_id=project.workspace_id,
                owned_by=create_user,
                description_html=f"<p>{name}</p>",
            )
            ProjectPage.objects.create(project=project, page=created, workspace_id=project.workspace_id)
            return created

        guion = page("Guion reel", folder)
        sub = page("Mayo", folder, kind=Page.FOLDER_KIND)
        nested = page("Brief mayo", sub)
        secret = page("Interno")
        archived = page("Viejo", folder)
        archived.archived_at = timezone.now().date()
        archived.save()

        client = as_user(cliente)
        names = sorted(d["name"] for d in client.get(f"/api/public/portal/{project.id}/documents/").json()["documents"])

        assert names == ["Brief mayo", "Guion reel"]
        doc = client.get(f"/api/public/portal/{project.id}/documents/{nested.id}/").json()
        assert doc["description_html"] == "<p>Brief mayo</p>"
        assert client.get(f"/api/public/portal/{project.id}/documents/{secret.id}/").status_code == 404
        assert client.get(f"/api/public/portal/{project.id}/documents/{guion.id}/").status_code == 200

        # an archived "Cliente" folder hides everything inside it
        folder.archived_at = timezone.now().date()
        folder.save()
        assert client.get(f"/api/public/portal/{project.id}/documents/").json()["documents"] == []
        assert client.get(f"/api/public/portal/{project.id}/documents/{guion.id}/").status_code == 404


@pytest.mark.contract
class TestInvites:
    @pytest.mark.django_db
    def test_turning_the_portal_on_invites_every_client_once(self, workspace, create_user, emails):
        push(workspace, [brand(KFC, "KFC", clients=["a@kfc.test", "b@kfc.test"])])
        project_id = mapping_of(KFC).project_id
        emails.reset_mock()
        url = f"/api/workspaces/{workspace.slug}/projects/{project_id}/zil-portal/"

        on = as_user(create_user).patch(url, {"enabled": True}, format="json")
        as_user(create_user).patch(url, {"enabled": True}, format="json")

        assert on.status_code == 200 and on.json()["enabled"] is True
        assert sorted(call.args[0][0] for call in emails.call_args_list) == ["a@kfc.test", "b@kfc.test"]
        assert "/spaces/portal/invite/" in emails.call_args.args[5]
        assert {c["status"] for c in on.json()["clients"]} == {"invited"}

    @pytest.mark.django_db
    def test_a_client_added_to_a_portal_that_is_on_is_invited_when_the_roster_is_kept(
        self, workspace, kfc, emails, django_capture_on_commit_callbacks
    ):
        emails.reset_mock()
        with django_capture_on_commit_callbacks(execute=True):
            response = push(workspace, [brand(KFC, "KFC", clients=["cliente@kfc.test", "nuevo@kfc.test"])])

        assert [call.args[0] for call in emails.call_args_list] == [["nuevo@kfc.test"]]
        access = {c["email"]: c["status"] for c in response["brands"][0]["clients"]}
        assert access == {"cliente@kfc.test": "never", "nuevo@kfc.test": "never"}  # computed before the commit
        assert ZilBrandClient.objects.get(email="nuevo@kfc.test").invited_at is not None

    @pytest.mark.django_db
    def test_the_link_sets_the_password_once_signs_in_and_then_stops_working(self, workspace, kfc, create_user, emails):
        client_row = ZilBrandClient.objects.get(email="cliente@kfc.test")
        emails.reset_mock()
        as_user(create_user).post(
            f"/api/workspaces/{workspace.slug}/projects/{kfc.project_id}/zil-portal/clients/{client_row.id}/invite/"
        )
        token = emails.call_args.args[5].rsplit("/invite/", 1)[1]
        anon = APIClient()

        info = anon.get(f"/api/public/portal/invite/{token}/").json()
        weak = anon.post(f"/api/public/portal/invite/{token}/", {"password": "1234"}, format="json")
        good = anon.post(f"/api/public/portal/invite/{token}/", {"password": "Calendario-KFC-2026!"}, format="json")
        again = anon.post(f"/api/public/portal/invite/{token}/", {"password": "Otra-clave-larga-99"}, format="json")

        assert info == {
            "email": "cliente@kfc.test",
            "brand": "KFC",
            "project_id": str(kfc.project_id),
            "needs_password": True,
        }
        assert weak.status_code == 400
        assert good.status_code == 200 and good.json() == {"project_id": str(kfc.project_id)}
        user = User.objects.get(email="cliente@kfc.test")
        assert user.check_password("Calendario-KFC-2026!") and not user.is_password_autoset
        assert again.status_code == 404
        # signed in: the portal opens in the same session
        assert anon.get(f"/api/public/portal/{kfc.project_id}/").status_code == 200
        client_row.refresh_from_db()
        assert client_row.invite_token_hash == ""

    @pytest.mark.django_db
    def test_a_new_invite_replaces_the_old_and_a_week_old_one_has_expired(self, workspace, kfc, create_user, emails):
        client_row = ZilBrandClient.objects.get(email="cliente@kfc.test")
        resend = (
            f"/api/workspaces/{workspace.slug}/projects/{kfc.project_id}/zil-portal/clients/{client_row.id}/invite/"
        )
        as_user(create_user).post(resend)
        first = emails.call_args.args[5].rsplit("/invite/", 1)[1]
        as_user(create_user).post(resend)
        second = emails.call_args.args[5].rsplit("/invite/", 1)[1]

        assert APIClient().get(f"/api/public/portal/invite/{first}/").status_code == 404
        assert APIClient().get(f"/api/public/portal/invite/{second}/").status_code == 200
        ZilBrandClient.objects.filter(pk=client_row.pk).update(invited_at=timezone.now() - timedelta(days=8))
        assert APIClient().get(f"/api/public/portal/invite/{second}/").status_code == 404
        client_row.refresh_from_db()
        from plane.utils.zil_client_portal import access_status

        assert access_status(client_row) == "expired"

    @pytest.mark.django_db
    def test_a_paused_portal_sends_no_invite(self, workspace, kfc, create_user, emails):
        push(workspace, [brand(KFC, "KFC", clients=["cliente@kfc.test"], status_="archived")])
        client_row = ZilBrandClient.objects.get(email="cliente@kfc.test")
        emails.reset_mock()

        response = as_user(create_user).post(
            f"/api/workspaces/{workspace.slug}/projects/{kfc.project_id}/zil-portal/clients/{client_row.id}/invite/"
        )

        assert response.status_code == 400 and not emails.called


@pytest.mark.contract
class TestInviteHardening:
    def _token(self, workspace, kfc, create_user, emails):
        client_row = ZilBrandClient.objects.get(email="cliente@kfc.test")
        emails.reset_mock()
        as_user(create_user).post(
            f"/api/workspaces/{workspace.slug}/projects/{kfc.project_id}/zil-portal/clients/{client_row.id}/invite/"
        )
        return emails.call_args.args[5].rsplit("/invite/", 1)[1]

    @pytest.mark.django_db
    def test_a_link_stops_working_when_the_portal_is_turned_off(self, workspace, kfc, create_user, emails):
        token = self._token(workspace, kfc, create_user, emails)
        ZilClientPortal.objects.filter(project_id=kfc.project_id).update(enabled=False)

        assert APIClient().get(f"/api/public/portal/invite/{token}/").status_code == 404
        response = APIClient().post(
            f"/api/public/portal/invite/{token}/", {"password": "Calendario-KFC-2026!"}, format="json"
        )
        assert response.status_code == 404

    @pytest.mark.django_db
    def test_an_account_with_its_own_password_is_sent_to_sign_in_not_signed_in(
        self, workspace, kfc, create_user, emails
    ):
        user = User.objects.get(email="cliente@kfc.test")
        user.set_password("Su-propia-clave-2026")
        user.is_password_autoset = False
        user.save()
        token = self._token(workspace, kfc, create_user, emails)
        anon = APIClient()

        response = anon.post(f"/api/public/portal/invite/{token}/", {}, format="json")

        assert response.json() == {"project_id": str(kfc.project_id), "sign_in": True}
        assert anon.get(f"/api/public/portal/{kfc.project_id}/").status_code in (401, 403)
        user.refresh_from_db()
        assert user.check_password("Su-propia-clave-2026")
        assert anon.post(f"/api/public/portal/invite/{token}/", {}, format="json").status_code == 404

    @pytest.mark.django_db
    def test_a_link_is_spent_once_even_by_two_requests_at_the_same_time(self, workspace, kfc, create_user, emails):
        from plane.utils.zil_client_portal import client_for_token, use_invite

        token = self._token(workspace, kfc, create_user, emails)
        first, second = client_for_token(token), client_for_token(token)

        assert use_invite(first) is True
        assert use_invite(second) is False


@pytest.mark.contract
class TestRedirect:
    @pytest.mark.django_db
    def test_a_client_without_a_workspace_lands_on_the_portal_and_skips_onboarding(self, kfc, cliente):
        assert cliente.profile.is_onboarded
        assert get_redirection_path(cliente) == "spaces/portal"
        settings_body = as_user(cliente).get("/api/users/me/settings/").json()
        assert settings_body["workspace"]["zil_portal_client"] is True

    @pytest.mark.django_db
    def test_a_client_who_is_also_on_a_team_keeps_going_to_their_workspace(self, kfc, cliente, create_user):
        other = Workspace.objects.create(name="Otra", slug="otra", owner=create_user)
        WorkspaceMember.objects.create(workspace=other, member=cliente, role=15)

        assert get_redirection_path(cliente) == "otra"
