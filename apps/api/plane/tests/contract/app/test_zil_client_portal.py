# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import json
from datetime import timedelta
from unittest import mock

import pytest
import requests
from django.core.cache import cache
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
    IssueLink,
    IssueView,
    Label,
    Notification,
    Page,
    Profile,
    ProjectMember,
    ProjectPage,
    State,
    User,
    Workspace,
    WorkspaceMember,
    ZilBrandClient,
    ZilBrandOps,
    ZilBrandProject,
    ZilChangeDraft,
    ZilClientPortal,
    ZilCommentMoment,
    ZilPageComment,
    ZilPostReview,
)
from plane.utils.zil_client_portal import (
    CLIENT_FOLDER,
    CONTENT_LABELS,
    CONTENT_STATES,
    REVIEW_STATE,
    VISIBLE_LABEL,
    dispatch_portal_events,
)
from plane.bgtasks.work_item_link_task import crawl_work_item_link_title
from plane.bgtasks.zil_drive_task import check_drive_link, check_portal_drive_links
from plane.utils.zil_client import ZilUnavailable
from plane.utils.zil_drive import drive_file_id

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


def send_round(client, project, issue, changes):
    """The client's way to comment: drafts, then "Enviar cambios" (confirmed). The send's response."""
    base = f"/api/public/portal/{project.id}/posts/{issue.id}"
    for change in changes:
        drafted = client.post(f"{base}/drafts/", change, format="json")
        assert drafted.status_code == status.HTTP_201_CREATED, drafted.data
    return client.post(f"{base}/send-changes/", {"confirm": True}, format="json")


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
        assert view.display_filters["calendar"] == {"layout": "month", "show_weekends": True}
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
                "unit": "zil",
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
        assert set(post) == {
            "id",
            "name",
            "publish_date",
            "status",
            "status_color",
            "network",
            "labels",
            "thumbnail",
            "review",
        }
        assert post["review"] is None  # worked out only for the posts to review
        assert post["network"] == "Instagram" and post["status"] == "preparing"
        assert [label["name"] for label in post["labels"]] == ["Instagram"]
        assert body["to_review"] == []

    @pytest.mark.django_db
    def test_the_review_strip_and_the_four_plain_statuses(self, kfc, cliente):
        project = kfc.project
        review = item(project, "Carrusel", state_name=REVIEW_STATE)
        item(project, "scheduled", state_name="Programado", target_date=timezone.now().date())
        item(project, "Salió", state_name="Publicado", target_date=timezone.now().date())

        body = as_user(cliente).get(f"/api/public/portal/{project.id}/posts/").json()

        assert [p["id"] for p in body["to_review"]] == [str(review.id)]
        assert body["to_review"][0]["status"] == "review"
        assert sorted(p["status"] for p in body["posts"]) == ["published", "scheduled"]

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
        issue = item(project, "Reel", state_name=REVIEW_STATE)
        IssueComment.objects.create(
            issue=issue, project=project, comment_html="<p>interno</p>", actor=create_user, access="INTERNAL"
        )
        IssueComment.objects.create(
            issue=issue, project=project, comment_html="<p>¿te gusta?</p>", actor=create_user, access="EXTERNAL"
        )
        url = f"/api/public/portal/{project.id}/posts/{issue.id}/comments/"

        with mock.patch("plane.space.views.zil_portal.issue_activity.delay") as activity:
            sent = send_round(as_user(cliente), project, issue, [{"text": "Me encanta\n<b>sí</b>"}])
            one_by_one = as_user(cliente).post(url, {"text": "suelto"}, format="json")
        comments = as_user(cliente).get(url).json()["comments"]

        assert sent.status_code == status.HTTP_201_CREATED
        # a client's comment only goes as part of a round
        assert one_by_one.status_code == status.HTTP_403_FORBIDDEN
        activity.assert_called_once()
        stored = IssueComment.objects.get(pk=sent.json()["comments"][0]["id"])
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


def folder_page(project, owner, name, parent, kind=Page.PAGE_KIND):
    created = Page.objects.create(
        name=name,
        parent=parent,
        kind=kind,
        workspace_id=project.workspace_id,
        owned_by=owner,
        description_html=f"<p>{name}</p>",
    )
    ProjectPage.objects.create(project=project, page=created, workspace_id=project.workspace_id)
    return created


@pytest.mark.contract
class TestDocumentTreeAndComments:
    @pytest.mark.django_db
    def test_the_documents_keep_the_folder_tree(self, kfc, cliente, create_user):
        project = kfc.project
        root = ZilClientPortal.objects.get(project=project).pages_folder
        mayo = folder_page(project, create_user, "Mayo", root, kind=Page.FOLDER_KIND)
        brief = folder_page(project, create_user, "Brief", mayo)
        guion = folder_page(project, create_user, "Guion", root)

        body = as_user(cliente).get(f"/api/public/portal/{project.id}/documents/").json()

        assert body["folders"] == [{"id": str(mayo.id), "name": "Mayo", "parent_id": None}]
        parents = {d["name"]: d["parent_id"] for d in body["documents"]}
        assert parents == {"Brief": str(mayo.id), "Guion": None}
        assert str(brief.id) and str(guion.id)

    @pytest.mark.django_db
    def test_client_and_team_talk_on_a_document_and_each_side_hears_by_email(
        self, workspace, kfc, cliente, create_user, emails, django_capture_on_commit_callbacks
    ):
        project = kfc.project
        ZilBrandOps.objects.create(zil_brand_id=KFC).community_managers.add(create_user)
        root = ZilClientPortal.objects.get(project=project).pages_folder
        guion = folder_page(project, create_user, "Guion", root)
        portal_url = f"/api/public/portal/{project.id}/documents/{guion.id}/comments/"
        team_url = f"/api/workspaces/{workspace.slug}/projects/{project.id}/pages/{guion.id}/zil-client-comments/"
        emails.reset_mock()

        asked = as_user(cliente).post(portal_url, {"text": "¿Podemos cambiar la escena 2?"}, format="json")
        assert asked.status_code == 201
        assert emails.call_args.args[0] == [create_user.email]

        team_view = as_user(create_user).get(team_url).json()
        assert [c["comment_html"] for c in team_view] == ["<p>¿Podemos cambiar la escena 2?</p>"]
        assert team_view[0]["access"] == "EXTERNAL" and team_view[0]["actor"] == str(cliente.id)

        emails.reset_mock()
        with django_capture_on_commit_callbacks(execute=True):
            answered = as_user(create_user).post(team_url, {"comment_html": "<p>Sí, va <b>hoy</b></p>"}, format="json")
        assert answered.status_code == 201
        assert emails.call_args.args[0] == ["cliente@kfc.test"]

        conversation = as_user(cliente).get(portal_url).json()["comments"]
        assert [c["is_team"] for c in conversation] == [False, True]
        assert conversation[1]["html"] == "<p>Sí, va <b>hoy</b></p>"

    @pytest.mark.django_db
    def test_only_pages_of_the_folder_have_the_conversation_and_only_the_author_edits(
        self, workspace, kfc, cliente, create_user
    ):
        project = kfc.project
        root = ZilClientPortal.objects.get(project=project).pages_folder
        outside = folder_page(project, create_user, "Interno", None)
        guion = folder_page(project, create_user, "Guion", root)
        base = f"/api/workspaces/{workspace.slug}/projects/{project.id}/pages"

        assert as_user(create_user).get(f"{base}/{outside.id}/zil-client-comments/").status_code == 404
        assert (
            as_user(cliente)
            .post(f"/api/public/portal/{project.id}/documents/{outside.id}/comments/", {"text": "x"}, format="json")
            .status_code
            == 404
        )
        theirs = ZilPageComment.objects.create(
            page=guion, project=project, workspace_id=project.workspace_id, actor=cliente, comment_html="<p>a</p>"
        )
        assert (
            as_user(create_user)
            .patch(f"{base}/{guion.id}/zil-client-comments/{theirs.id}/", {"comment_html": "<p>b</p>"}, format="json")
            .status_code
            == 404
        )


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
            "unit": "zil",
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


def tokens_sent(emails):
    """The invite tokens in the emails the mock captured, in order."""
    return [call.args[5].rsplit("/invite/", 1)[1] for call in emails.call_args_list if "/invite/" in call.args[5]]


@pytest.mark.contract
class TestClientWithSeveralBrands:
    """One contact invited to the portal of several brands: one account, one access per brand."""

    def _two_brands(self, workspace, wendys_clients=("lucia@x.test",), wendys_status="active"):
        push(
            workspace,
            [
                brand(KFC, "KFC", clients=["lucia@x.test"]),
                brand(WENDYS, "Wendys", clients=list(wendys_clients), status_=wendys_status),
            ],
        )

    def _signed_in(self):
        user = User.objects.get(email="lucia@x.test")
        user.last_login_time = timezone.now()
        user.is_password_autoset = False
        user.save()
        return user

    @pytest.mark.django_db
    def test_one_account_with_an_access_per_brand_and_mis_marcas_lists_them(self, workspace, emails):
        self._two_brands(workspace)
        turn_on(KFC)
        turn_on(WENDYS)
        lucia = self._signed_in()

        assert User.objects.filter(email="lucia@x.test").count() == 1
        assert set(ZilBrandClient.objects.filter(email="lucia@x.test").values_list("user_id", flat=True)) == {lucia.id}
        brands = as_user(lucia).get("/api/public/portal/").json()["brands"]
        assert [(b["name"], b["paused"]) for b in brands] == [("KFC", False), ("Wendys", False)]
        for b in brands:
            assert as_user(lucia).get(f"/api/public/portal/{b['id']}/posts/").status_code == 200

    @pytest.mark.django_db
    def test_each_brand_only_shows_its_own_posts_and_documents(self, workspace, create_user, emails):
        self._two_brands(workspace)
        turn_on(KFC)
        turn_on(WENDYS)
        lucia = self._signed_in()
        kfc, wendys = mapping_of(KFC).project, mapping_of(WENDYS).project
        kfc_post = item(kfc, "Reel KFC", target_date=timezone.now().date())
        item(wendys, "Reel Wendys", target_date=timezone.now().date())

        kfc_posts = as_user(lucia).get(f"/api/public/portal/{kfc.id}/posts/").json()["posts"]
        assert [p["name"] for p in kfc_posts] == ["Reel KFC"]
        # a post of one brand is not reachable through the other brand's portal
        assert as_user(lucia).get(f"/api/public/portal/{wendys.id}/posts/{kfc_post.id}/").status_code == 404

    @pytest.mark.django_db
    def test_pausing_one_brand_leaves_the_other_open(self, workspace, emails):
        self._two_brands(workspace)
        turn_on(KFC)
        turn_on(WENDYS)
        lucia = self._signed_in()

        self._two_brands(workspace, wendys_status="archived")

        brands = {b["name"]: b["paused"] for b in as_user(lucia).get("/api/public/portal/").json()["brands"]}
        assert brands == {"KFC": False, "Wendys": True}
        assert as_user(lucia).get(f"/api/public/portal/{mapping_of(KFC).project_id}/posts/").status_code == 200
        paused = as_user(lucia).get(f"/api/public/portal/{mapping_of(WENDYS).project_id}/posts/")
        assert paused.status_code == 403 and paused.json()["paused"] is True

    @pytest.mark.django_db
    def test_removing_her_from_one_brand_keeps_the_other(self, workspace, emails):
        self._two_brands(workspace)
        turn_on(KFC)
        turn_on(WENDYS)
        lucia = self._signed_in()

        self._two_brands(workspace, wendys_clients=())

        assert [b["name"] for b in as_user(lucia).get("/api/public/portal/").json()["brands"]] == ["KFC"]
        assert as_user(lucia).get(f"/api/public/portal/{mapping_of(WENDYS).project_id}/").status_code == 404
        assert as_user(lucia).get(f"/api/public/portal/{mapping_of(KFC).project_id}/").status_code == 200
        assert User.objects.get(email="lucia@x.test").is_active

    @pytest.mark.django_db
    def test_an_invite_per_brand_one_password_for_both(self, workspace, create_user, emails):
        self._two_brands(workspace)
        emails.reset_mock()
        for brand_id in (KFC, WENDYS):
            as_user(create_user).patch(
                f"/api/workspaces/{workspace.slug}/projects/{mapping_of(brand_id).project_id}/zil-portal/",
                {"enabled": True},
                format="json",
            )
        kfc_token, wendys_token = tokens_sent(emails)
        anon = APIClient()

        assert anon.get(f"/api/public/portal/invite/{kfc_token}/").json()["brand"] == "KFC"
        assert anon.get(f"/api/public/portal/invite/{wendys_token}/").json()["brand"] == "Wendys"
        accepted = anon.post(
            f"/api/public/portal/invite/{kfc_token}/", {"password": "Dos-Marcas-Una-Clave-26"}, format="json"
        )
        assert accepted.status_code == 200

        # the other link is spent with it, and the session opens both brands
        assert anon.get(f"/api/public/portal/invite/{wendys_token}/").status_code == 404
        assert [b["name"] for b in anon.get("/api/public/portal/").json()["brands"]] == ["KFC", "Wendys"]
        assert anon.get(f"/api/public/portal/{mapping_of(WENDYS).project_id}/").status_code == 200

        # a new invite to Wendys now just sends her to sign in with the password she chose
        wendys_row = ZilBrandClient.objects.get(email="lucia@x.test", brand_project__zil_brand_id=WENDYS)
        emails.reset_mock()
        as_user(create_user).post(
            f"/api/workspaces/{workspace.slug}/projects/{mapping_of(WENDYS).project_id}/zil-portal/clients/{wendys_row.id}/invite/"
        )
        resent = APIClient().post(f"/api/public/portal/invite/{tokens_sent(emails)[0]}/", {}, format="json")
        assert resent.json() == {"project_id": str(mapping_of(WENDYS).project_id), "sign_in": True}

    @pytest.mark.django_db
    def test_on_the_team_of_one_brand_and_client_of_another(self, workspace, emails):
        team = User.objects.create(email="lucia@x.test", username="lucia-team")
        WorkspaceMember.objects.create(workspace=workspace, member=team, role=15)
        push(
            workspace,
            [
                brand(KFC, "KFC", team=["lucia@x.test"]),
                brand(WENDYS, "Wendys", clients=["lucia@x.test"]),
            ],
        )
        turn_on(KFC)
        turn_on(WENDYS)

        # a client of Wendys (no membership there), a member of KFC's team (preview of its portal)
        assert as_user(team).get(f"/api/public/portal/{mapping_of(WENDYS).project_id}/").json()["preview"] is False
        assert as_user(team).get(f"/api/public/portal/{mapping_of(KFC).project_id}/").json()["preview"] is True
        assert [b["name"] for b in as_user(team).get("/api/public/portal/").json()["brands"]] == ["Wendys"]
        # signing in to Ops takes her to her workspace, not the portal (a team account is onboarded)
        Profile.objects.update_or_create(user=team, defaults={"is_onboarded": True})
        assert get_redirection_path(team) == workspace.slug


@pytest.mark.contract
class TestReviewFixes:
    @pytest.mark.django_db
    def test_a_private_page_or_folder_inside_the_client_folder_never_reaches_the_client(
        self, kfc, cliente, create_user
    ):
        project = kfc.project
        root = ZilClientPortal.objects.get(project=project).pages_folder
        shared = folder_page(project, create_user, "Guion", root)
        draft = folder_page(project, create_user, "Borrador interno", root)
        draft.access = Page.PRIVATE_ACCESS
        draft.save()
        secret_folder = folder_page(project, create_user, "Privada", root, kind=Page.FOLDER_KIND)
        secret_folder.access = Page.PRIVATE_ACCESS
        secret_folder.save()
        inside_secret = folder_page(project, create_user, "Dentro de privada", secret_folder)

        body = as_user(cliente).get(f"/api/public/portal/{project.id}/documents/").json()

        assert [d["name"] for d in body["documents"]] == ["Guion"]
        assert body["folders"] == []
        for page in (draft, inside_secret):
            assert as_user(cliente).get(f"/api/public/portal/{project.id}/documents/{page.id}/").status_code == 404
        assert as_user(cliente).get(f"/api/public/portal/{project.id}/documents/{shared.id}/").status_code == 200

    @pytest.mark.django_db
    def test_a_cliente_folder_the_team_already_had_is_not_adopted(self, workspace, create_user, emails):
        push(workspace, [brand(KFC, "KFC")])
        project = mapping_of(KFC).project
        ZilClientPortal.objects.filter(project=project).delete(soft=False)
        theirs = folder_page(project, create_user, "Cliente", None, kind=Page.FOLDER_KIND)

        push(workspace, [brand(KFC, "KFC")])

        portal = ZilClientPortal.objects.get(project=project)
        assert portal.pages_folder_id != theirs.id
        assert portal.pages_folder.external_source == "zil_client_portal"

    @pytest.mark.django_db
    def test_making_an_internal_comment_external_emails_the_client(self, kfc, cliente, create_user, emails):
        issue = item(kfc.project, "Reel")
        comment = IssueComment.objects.create(
            issue=issue, project=kfc.project, comment_html="<p>Listo</p>", actor=create_user, access="EXTERNAL"
        )
        emails.reset_mock()

        dispatch_portal_events(
            "comment.activity.updated",
            issue.id,
            create_user.id,
            [],
            project_id=kfc.project_id,
            requested_data='{"access": "EXTERNAL"}',
            current_instance=f'{{"id": "{comment.id}", "access": "INTERNAL"}}',
        )

        assert [call.args[0] for call in emails.call_args_list] == [["cliente@kfc.test"]]

    @pytest.mark.django_db
    def test_showing_an_item_that_already_waits_for_review_emails_the_client(self, kfc, cliente, create_user, emails):
        issue = item(kfc.project, "Carrusel", state_name=REVIEW_STATE)
        emails.reset_mock()

        dispatch_portal_events(
            "issue.activity.updated",
            issue.id,
            create_user.id,
            [mock.Mock(field="labels", verb="updated", new_value=VISIBLE_LABEL)],
            project_id=kfc.project_id,
        )

        assert [call.args[0] for call in emails.call_args_list] == [["cliente@kfc.test"]]

    @pytest.mark.django_db
    def test_a_project_without_a_portal_costs_one_query_and_sends_nothing(self, workspace, create_user, emails):
        push(workspace, [brand(KFC, "KFC")])
        project = mapping_of(KFC).project
        issue = item(project, "Reel", state_name=REVIEW_STATE)
        emails.reset_mock()

        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as queries:
            dispatch_portal_events(
                "issue.activity.updated",
                issue.id,
                create_user.id,
                [mock.Mock(field="state", new_value=REVIEW_STATE)],
                project_id=project.id,
            )

        assert len(queries) == 1 and not emails.called


@pytest.mark.contract
class TestPortalUnit:
    @pytest.mark.django_db
    def test_a_meraki_unit_brand_wears_meraki_and_the_rest_zil(self, create_user, emails):
        from plane.utils.zil_client_portal import portal_unit

        assert portal_unit("meraki") == "meraki" and portal_unit("meraki-studio") == "meraki"
        assert portal_unit("zil") == "zil" and portal_unit("marketwise") == "zil"
        meraki = Workspace.objects.create(name="Meraki", slug="meraki", owner=create_user)
        WorkspaceMember.objects.create(workspace=meraki, member=create_user, role=20)
        push(meraki, [brand(KFC, "KFC", clients=["cliente@kfc.test"])])
        turn_on(KFC)
        lucia = User.objects.get(email="cliente@kfc.test")

        assert as_user(lucia).get("/api/public/portal/").json()["brands"][0]["unit"] == "meraki"
        assert as_user(lucia).get(f"/api/public/portal/{mapping_of(KFC).project_id}/").json()["unit"] == "meraki"


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


DRIVE_ID = "1AbCdEfGhIjKlMnOpQrStUv"
DRIVE_GET = "plane.utils.zil_drive.requests.get"
WORKSPACE_POST = "plane.utils.zil_drive._post"
ACTIVITY = "plane.space.views.zil_portal.issue_activity.delay"


def drive_link(issue, by, url=f"https://drive.google.com/file/d/{DRIVE_ID}/view?usp=sharing", title="Reel final"):
    link = IssueLink(issue=issue, project=issue.project, workspace_id=issue.workspace_id, url=url, title=title)
    link.save(created_by_id=by.id if by else None, disable_auto_set_user=by is None)
    return link


def workspace_token(status_code=200, token="ya29.drive-token"):
    response = mock.Mock(status_code=status_code)
    expires = (timezone.now() + timedelta(hours=1)).isoformat()
    response.json.return_value = {"accessToken": token, "expiresAt": expires}
    return response


def drive_meta(status_code=200, mime="video/mp4", name="reel-final.mp4"):
    response = mock.Mock(status_code=status_code)
    response.json.return_value = {"name": name, "mimeType": mime}
    return response


def video(issue, name="reel.mp4"):
    return FileAsset.objects.create(
        asset=f"kfc/{name}",
        attributes={"name": name, "type": "video/mp4", "size": 10},
        entity_type=FileAsset.EntityTypeContext.ISSUE_ATTACHMENT,
        issue=issue,
        project=issue.project,
        workspace_id=issue.workspace_id,
        is_uploaded=True,
    )


@pytest.fixture
def workspace_bridge(monkeypatch):
    monkeypatch.setenv("ZIL_BASE_URL", "https://zil.test")
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def cm(db):
    return User.objects.create(email="cm@zil.test", username="cm-zil")


@pytest.mark.contract
class TestDriveFileIds:
    @pytest.mark.parametrize(
        "url,expected",
        [
            (f"https://drive.google.com/file/d/{DRIVE_ID}/view?usp=sharing", DRIVE_ID),
            (f"https://drive.google.com/file/d/{DRIVE_ID}", DRIVE_ID),
            (f"https://drive.google.com/open?id={DRIVE_ID}", DRIVE_ID),
            (f"https://drive.google.com/uc?export=download&id={DRIVE_ID}", DRIVE_ID),
            (f"http://drive.google.com/file/d/{DRIVE_ID}/view", None),
            (f"https://drive.google.com.evil.test/file/d/{DRIVE_ID}/view", None),
            (f"https://evil.test/?u=https://drive.google.com/file/d/{DRIVE_ID}", None),
            ("https://drive.google.com/drive/folders/1AbCdEfGhIjKlMnOp", None),
            ("https://drive.google.com/file/d/short/view", None),
            ('https://drive.google.com/file/d/bad"id<script>xx/view', None),
        ],
    )
    def test_only_drive_file_links_give_a_file_id(self, url, expected):
        assert drive_file_id(url) == expected


@pytest.mark.contract
class TestDriveVideos:
    @pytest.mark.django_db
    def test_a_drive_video_plays_through_ops_read_as_whoever_linked_it(self, kfc, cliente, cm, workspace_bridge):
        project = kfc.project
        issue = item(project, "Reel")
        uploaded = video(issue)
        drive_link(issue, cm)
        drive_link(issue, cm, url=f"https://drive.google.com/open?id={DRIVE_ID}", title="again")
        url = f"/api/public/portal/{project.id}/posts/{issue.id}/"

        with (
            mock.patch(WORKSPACE_POST, return_value=workspace_token()) as workspace,
            mock.patch(DRIVE_GET, return_value=drive_meta()) as google,
        ):
            response = as_user(cliente).get(url)
            as_user(cliente).get(url)

        media = response.json()["media"]
        assert [m["id"] for m in media] == [str(uploaded.id), f"drive:{DRIVE_ID}"]
        assert media[1] == {
            "id": f"drive:{DRIVE_ID}",
            "kind": "drive",
            "name": "reel-final.mp4",
            "type": "video/mp4",
            "url": f"/api/public/portal/{project.id}/posts/{issue.id}/drive/{DRIVE_ID}/",
        }
        # read as the person who pasted the link, with a token Workspace mints; once each, cached
        workspace.assert_called_once_with("/api/zil/drive-token", {"email": "cm@zil.test"})
        google.assert_called_once()
        assert google.call_args.kwargs["headers"] == {"Authorization": "Bearer ya29.drive-token"}
        # the Drive file is the post's media, not one more link
        assert response.json()["links"] == []
        # neither the token nor who pasted the link reach the client
        assert "ya29" not in response.content.decode() and "cm@zil.test" not in response.content.decode()

    @pytest.mark.django_db
    def test_no_token_or_no_author_shows_the_video_as_being_processed_and_warns_the_team(
        self, kfc, cliente, cm, workspace_bridge
    ):
        project = kfc.project
        refused = item(project, "Reel")
        refused_link = drive_link(refused, cm)
        orphan = item(project, "Otro")
        orphan_link = drive_link(orphan, None)

        with (
            mock.patch(WORKSPACE_POST, return_value=workspace_token(status_code=404)) as workspace,
            mock.patch(DRIVE_GET) as google,
        ):
            first = as_user(cliente).get(f"/api/public/portal/{project.id}/posts/{refused.id}/").json()["media"][0]
            second = as_user(cliente).get(f"/api/public/portal/{project.id}/posts/{orphan.id}/").json()["media"][0]

        assert first == {"id": f"drive:{DRIVE_ID}", "kind": "unavailable", "name": "Reel final", "type": "", "url": ""}
        assert second["kind"] == "unavailable"
        workspace.assert_called_once()  # nobody to read the orphan link as
        google.assert_not_called()
        # both are certain: the team sees them in Ops
        for link in (refused_link, orphan_link):
            link.refresh_from_db()
            assert link.metadata["zil_drive"]["status"] == "broken"

    @pytest.mark.django_db
    def test_workspace_or_google_down_does_not_break_the_post(self, kfc, cliente, cm, workspace_bridge):
        project = kfc.project
        issue = item(project, "Reel")
        link = drive_link(issue, cm)
        url = f"/api/public/portal/{project.id}/posts/{issue.id}/"

        with mock.patch(WORKSPACE_POST, side_effect=ZilUnavailable()):
            down = as_user(cliente).get(url)
        cache.clear()
        with (
            mock.patch(WORKSPACE_POST, return_value=workspace_token()),
            mock.patch(DRIVE_GET, side_effect=requests.ConnectionError("down")),
        ):
            google_down = as_user(cliente).get(url)

        assert down.status_code == google_down.status_code == 200
        assert down.json()["media"][0]["kind"] == google_down.json()["media"][0]["kind"] == "unavailable"
        # an outage is not a broken link: no warning for the team
        link.refresh_from_db()
        assert "zil_drive" not in link.metadata


@pytest.mark.contract
class TestDriveWarnings:
    @pytest.mark.django_db
    def test_google_not_found_is_broken_and_a_fixed_file_clears_it(self, kfc, cliente, cm, workspace_bridge):
        project = kfc.project
        issue = item(project, "Reel")
        link = drive_link(issue, cm)

        with (
            mock.patch(WORKSPACE_POST, return_value=workspace_token()),
            mock.patch(DRIVE_GET, return_value=drive_meta(status_code=404)),
        ):
            as_user(cliente).get(f"/api/public/portal/{project.id}/posts/{issue.id}/")
        link.refresh_from_db()
        assert link.metadata["zil_drive"]["status"] == "broken"

        # the team fixes it and presses refresh: checked again without the cache
        with (
            mock.patch(WORKSPACE_POST, return_value=workspace_token()),
            mock.patch(DRIVE_GET, return_value=drive_meta()),
        ):
            check_drive_link(str(link.id))
        link.refresh_from_db()
        assert link.metadata["zil_drive"]["status"] == "ok"

    @pytest.mark.django_db
    def test_the_periodic_check_covers_what_clients_see_from_a_week_ago(self, kfc, cm, workspace_bridge):
        project = kfc.project
        upcoming = item(project, "Próximo", target_date=timezone.now().date() + timedelta(days=3))
        undated = item(project, "Sin fecha")
        old = item(project, "Viejo", target_date=timezone.now().date() - timedelta(days=30))
        hidden = item(project, "Interno", visible=False)
        links = {issue.name: drive_link(issue, cm) for issue in (upcoming, undated, old, hidden)}

        with (
            mock.patch(WORKSPACE_POST, return_value=workspace_token()),
            mock.patch(DRIVE_GET, return_value=drive_meta(status_code=403)),
        ):
            checked = check_portal_drive_links()

        assert checked == 2
        statuses = {}
        for name, link in links.items():
            link.refresh_from_db()
            statuses[name] = (link.metadata.get("zil_drive") or {}).get("status")
        assert statuses == {"Próximo": "broken", "Sin fecha": "broken", "Viejo": None, "Interno": None}

    @pytest.mark.django_db
    def test_ops_lists_the_brands_items_with_a_broken_video(self, kfc, cm, create_user, workspace_bridge):
        project = kfc.project
        ProjectMember.objects.update_or_create(
            project=project,
            member=create_user,
            defaults={"workspace_id": project.workspace_id, "role": 15, "is_active": True},
        )
        broken = item(project, "Reel")
        fine = item(project, "Carrusel")
        link = drive_link(broken, cm)
        drive_link(fine, cm)
        IssueLink.objects.filter(pk=link.pk).update(metadata={"zil_drive": {"status": "broken"}})
        IssueLink.objects.filter(issue=fine).update(metadata={"zil_drive": {"status": "ok"}})
        url = f"/api/workspaces/{project.workspace.slug}/projects/{project.id}/zil-portal/video-alerts/"

        response = as_user(create_user).get(url)

        assert response.status_code == 200
        assert response.json() == {
            "issues": {str(broken.id): [{"link_id": str(link.id), "title": "Reel final", "url": link.url}]}
        }

    @pytest.mark.django_db
    def test_a_new_drive_link_is_checked_after_its_crawl(self, kfc, cm):
        issue = item(kfc.project, "Reel")
        link = drive_link(issue, cm)

        with (
            mock.patch(
                "plane.bgtasks.work_item_link_task.crawl_google_drive_link_metadata", return_value={"title": "x"}
            ),
            mock.patch("plane.bgtasks.zil_drive_task.check_drive_link.delay") as check,
        ):
            crawl_work_item_link_title(str(link.id), link.url)

        check.assert_called_once_with(str(link.id))


@pytest.mark.contract
class TestDriveStream:
    def _upstream(self, status_code=206, body=b"0123456789"):
        upstream = mock.Mock(status_code=status_code)
        upstream.headers = {"Content-Length": str(len(body)), "Content-Range": "bytes 100-109/5000"}
        upstream.iter_content.return_value = iter([body])
        return upstream

    @pytest.mark.django_db
    def test_the_player_gets_the_video_in_pieces_read_as_whoever_linked_it(self, kfc, cliente, cm, workspace_bridge):
        project = kfc.project
        issue = item(project, "Reel")
        drive_link(issue, cm)
        url = f"/api/public/portal/{project.id}/posts/{issue.id}/drive/{DRIVE_ID}/"
        upstream = self._upstream()

        with (
            mock.patch(WORKSPACE_POST, return_value=workspace_token()),
            mock.patch(DRIVE_GET, side_effect=[drive_meta(), upstream, self._upstream()]) as google,
        ):
            response = as_user(cliente).get(url, HTTP_RANGE="bytes=100-")
            body = b"".join(response.streaming_content)
            as_user(cliente).get(url)

        assert response.status_code == 206 and body == b"0123456789"
        assert response["Content-Type"] == "video/mp4" and response["Content-Range"] == "bytes 100-109/5000"
        assert response["Accept-Ranges"] == "bytes"
        stream_call = google.call_args_list[1]
        assert stream_call.kwargs["params"]["alt"] == "media"
        # at most 8 MiB per request: the player asks for the next piece
        assert stream_call.kwargs["headers"] == {
            "Authorization": "Bearer ya29.drive-token",
            "Range": "bytes=100-8388707",
        }
        assert google.call_args_list[2].kwargs["headers"]["Range"] == "bytes=0-8388607"
        upstream.close.assert_called_once()

    @pytest.mark.django_db
    def test_only_files_linked_on_a_post_the_client_sees(self, kfc, cliente, cm, create_user, workspace_bridge):
        project = kfc.project
        issue = item(project, "Reel")
        hidden = item(project, "Interno", visible=False)
        drive_link(issue, cm)
        drive_link(hidden, cm, url="https://drive.google.com/file/d/1HiddenFileAbcdefghij/view")
        stranger = User.objects.create(email="otro@cliente.test", username="otro")
        base = f"/api/public/portal/{project.id}/posts"

        with mock.patch(WORKSPACE_POST, return_value=workspace_token()) as workspace, mock.patch(DRIVE_GET) as google:
            answers = [
                as_user(cliente).get(f"{base}/{issue.id}/drive/1SomeOtherFileOfTheDrive/").status_code,
                as_user(cliente).get(f"{base}/{hidden.id}/drive/1HiddenFileAbcdefghij/").status_code,
                as_user(stranger).get(f"{base}/{issue.id}/drive/{DRIVE_ID}/").status_code,
            ]

        assert answers == [404, 404, 404]
        workspace.assert_not_called()
        google.assert_not_called()

    @pytest.mark.django_db
    def test_a_file_that_is_not_a_video_or_an_image_is_not_streamed(self, kfc, cliente, cm, workspace_bridge):
        project = kfc.project
        issue = item(project, "Reel")
        drive_link(issue, cm)

        with (
            mock.patch(WORKSPACE_POST, return_value=workspace_token()),
            mock.patch(DRIVE_GET, return_value=drive_meta(mime="application/pdf", name="brief.pdf")) as google,
        ):
            response = as_user(cliente).get(f"/api/public/portal/{project.id}/posts/{issue.id}/drive/{DRIVE_ID}/")

        assert response.status_code == 404
        google.assert_called_once()  # the metadata only, never the bytes


@pytest.mark.contract
class TestCommentMoments:
    @pytest.mark.django_db
    def test_a_comment_at_a_second_of_an_uploaded_video(self, kfc, cliente):
        project = kfc.project
        issue = item(project, "Reel", state_name=REVIEW_STATE)
        clip = video(issue, "reel <v2>.mp4")
        url = f"/api/public/portal/{project.id}/posts/{issue.id}/comments/"

        with mock.patch(ACTIVITY) as activity:
            sent = send_round(
                as_user(cliente), project, issue, [{"text": "Cortar acá", "media": str(clip.id), "at": 62}]
            )
        comments = as_user(cliente).get(url).json()["comments"]

        assert sent.status_code == status.HTTP_201_CREATED
        created = sent.json()["comments"][0]
        stored = IssueComment.objects.get(pk=created["id"])
        # Ops and its emails read the moment from the text
        assert stored.comment_html == "<p><strong>1:02</strong> · reel &lt;v2&gt;.mp4</p><p>Cortar acá</p>"
        assert "1:02" in json.loads(activity.call_args.kwargs["requested_data"])["comment_html"]
        # the portal gets it apart, as its button
        assert created["moment"] == {"media": str(clip.id), "at": 62, "label": "1:02"}
        assert comments[0]["html"] == "<p>Cortar acá</p>" and comments[0]["moment"]["at"] == 62

    @pytest.mark.django_db
    def test_a_comment_at_a_second_of_a_drive_video(self, kfc, cliente, cm, workspace_bridge):
        project = kfc.project
        issue = item(project, "Reel", state_name=REVIEW_STATE)
        drive_link(issue, cm)

        with (
            mock.patch(WORKSPACE_POST, return_value=workspace_token()),
            mock.patch(DRIVE_GET, return_value=drive_meta()),
            mock.patch(ACTIVITY),
        ):
            sent = send_round(
                as_user(cliente), project, issue, [{"text": "Más rápido", "media": f"drive:{DRIVE_ID}", "at": 3725}]
            )

        assert sent.status_code == status.HTTP_201_CREATED
        created = sent.json()["comments"][0]
        assert created["moment"]["label"] == "1:02:05"
        assert ZilCommentMoment.objects.get(comment_id=created["id"]).media == f"drive:{DRIVE_ID}"

    @pytest.mark.django_db
    def test_a_moment_must_be_a_playable_video_of_this_post(self, kfc, cliente, cm, workspace_bridge):
        project = kfc.project
        issue = item(project, "Reel", state_name=REVIEW_STATE)
        other = item(project, "Otro")
        foreign = video(other, "otro.mp4")
        clip = video(issue)
        image = FileAsset.objects.create(
            asset="kfc/foto.jpg",
            attributes={"name": "foto.jpg", "type": "image/jpeg"},
            entity_type=FileAsset.EntityTypeContext.ISSUE_ATTACHMENT,
            issue=issue,
            project=project,
            workspace_id=project.workspace_id,
            is_uploaded=True,
        )
        drive_link(issue, cm)
        url = f"/api/public/portal/{project.id}/posts/{issue.id}/drafts/"

        bad = [
            {"media": str(foreign.id), "at": 1},  # another post's video
            {"media": str(image.id), "at": 1},  # not a video
            {"media": f"drive:{DRIVE_ID}", "at": 1},  # unavailable (the link's author can't open it)
            {"media": "drive:9ZzZzZzZzZzZzZz", "at": 1},  # not linked on the post
            {"media": str(clip.id), "at": -1},
            {"media": str(clip.id), "at": 24 * 60 * 60 + 1},
            {"media": str(clip.id), "at": "soon"},
            {"media": str(clip.id)},
        ]
        with (
            mock.patch(WORKSPACE_POST, return_value=workspace_token()),
            mock.patch(DRIVE_GET, return_value=drive_meta(status_code=404)),
            mock.patch(ACTIVITY) as activity,
        ):
            answers = [as_user(cliente).post(url, {"text": "x", **body}, format="json").status_code for body in bad]

        assert answers == [status.HTTP_400_BAD_REQUEST] * len(bad)
        activity.assert_not_called()
        assert not ZilChangeDraft.objects.filter(issue=issue).exists()


@pytest.mark.contract
class TestChangeRounds:
    def _review_url(self, project, issue):
        return f"/api/public/portal/{project.id}/posts/{issue.id}/"

    @pytest.mark.django_db
    def test_the_window_opens_the_first_time_the_post_goes_to_review_and_only_then(self, kfc, create_user):
        project = kfc.project
        issue = item(project, "Reel")
        review_state = State.objects.get(project=project, name=REVIEW_STATE)
        moved = [mock.Mock(field="state", verb="updated", new_value=REVIEW_STATE)]

        assert not ZilPostReview.objects.filter(issue=issue).exists()
        Issue.objects.filter(pk=issue.pk).update(state=review_state)
        dispatch_portal_events("issue.activity.updated", issue.id, create_user.id, moved, project_id=project.id)
        first = ZilPostReview.objects.get(issue=issue).started_at
        # back to the team and to review again: the same window, not a new one
        dispatch_portal_events("issue.activity.updated", issue.id, create_user.id, moved, project_id=project.id)

        assert ZilPostReview.objects.get(issue=issue).started_at == first

    @pytest.mark.django_db
    def test_a_post_shows_its_rounds_and_deadline_and_each_send_uses_one(self, kfc, cliente):
        project = kfc.project
        issue = item(project, "Reel", state_name=REVIEW_STATE)
        client = as_user(cliente)

        before = client.get(self._review_url(project, issue)).json()["review"]
        with mock.patch(ACTIVITY) as activity:
            first = send_round(client, project, issue, [{"text": "Uno"}, {"text": "Dos"}])

        started = ZilPostReview.objects.get(issue=issue).started_at
        assert before == {
            "rounds": 2,
            "used": 0,
            "left": 2,
            "deadline": (started + timedelta(hours=72)).isoformat(),
            "open": True,
            "reason": None,
        }
        assert first.status_code == status.HTTP_201_CREATED
        assert [c["html"] for c in first.json()["comments"]] == ["<p>Uno</p>", "<p>Dos</p>"]
        assert first.json()["review"]["left"] == 1
        assert not ZilChangeDraft.objects.filter(issue=issue).exists()
        # one activity per comment; only the first carries the team's notice for the round
        rounds = [json.loads(call.kwargs["requested_data"])["zil_round"] for call in activity.call_args_list]
        assert [r["first"] for r in rounds] == [True, False] and rounds[0]["round"] == 1

    @pytest.mark.django_db
    def test_the_team_hears_a_round_once(self, kfc, cliente, create_user, emails):
        project = kfc.project
        ops = ZilBrandOps.objects.create(zil_brand_id=KFC)
        ops.community_managers.add(create_user)
        issue = item(project, "Reel", state_name=REVIEW_STATE)
        with mock.patch(ACTIVITY) as activity:
            send_round(as_user(cliente), project, issue, [{"text": "Uno"}, {"text": "Dos"}])
        emails.reset_mock()

        for call in activity.call_args_list:
            data = json.loads(call.kwargs["requested_data"])
            dispatch_portal_events(
                "comment.activity.created",
                issue.id,
                cliente.id,
                [mock.Mock(field="comment", issue_comment_id=data["id"])],
                project_id=project.id,
                requested_data=call.kwargs["requested_data"],
            )

        notice = Notification.objects.get(receiver=create_user)
        assert "(ronda 1)" in notice.title and "Uno" in notice.message_stripped and "Dos" in notice.message_stripped
        emails.assert_called_once()

    @pytest.mark.django_db
    def test_drafts_are_the_clients_own_until_sent(self, kfc, cliente, create_user):
        project = kfc.project
        issue = item(project, "Reel", state_name=REVIEW_STATE)
        other = User.objects.create(email="socia@kfc.test", username="socia")
        ZilBrandClient.objects.create(brand_project=kfc, email=other.email, user=other)
        base = f"/api/public/portal/{project.id}/posts/{issue.id}"

        draft = as_user(cliente).post(f"{base}/drafts/", {"text": "Borrador"}, format="json").json()
        edited = as_user(cliente).patch(f"{base}/drafts/{draft['id']}/", {"text": "Mejor así"}, format="json")

        assert edited.json()["text"] == "Mejor así"
        assert as_user(other).get(f"{base}/drafts/").json()["drafts"] == []
        assert as_user(other).delete(f"{base}/drafts/{draft['id']}/").status_code == 404
        assert as_user(create_user).get(f"{base}/drafts/").status_code == 403
        assert as_user(cliente).get(f"{base}/comments/").json()["comments"] == []
        assert as_user(cliente).delete(f"{base}/drafts/{draft['id']}/").status_code == 204

    @pytest.mark.django_db
    def test_sending_needs_the_yes_and_something_to_send(self, kfc, cliente):
        project = kfc.project
        issue = item(project, "Reel", state_name=REVIEW_STATE)
        base = f"/api/public/portal/{project.id}/posts/{issue.id}"
        as_user(cliente).post(f"{base}/drafts/", {"text": "Uno"}, format="json")

        unconfirmed = as_user(cliente).post(f"{base}/send-changes/", {}, format="json")
        ZilChangeDraft.objects.all().delete(soft=False)
        empty = as_user(cliente).post(f"{base}/send-changes/", {"confirm": True}, format="json")

        assert unconfirmed.status_code == empty.status_code == status.HTTP_400_BAD_REQUEST
        assert ZilPostReview.objects.get(issue=issue).rounds_used == 0

    @pytest.mark.django_db
    def test_changes_close_when_the_rounds_are_used_the_time_is_up_or_it_never_went_to_review(self, kfc, cliente):
        project = kfc.project
        used_up = item(project, "Usado", state_name=REVIEW_STATE)
        late = item(project, "Tarde", state_name=REVIEW_STATE)
        early = item(project, "Temprano")
        client = as_user(cliente)
        with mock.patch(ACTIVITY):
            send_round(client, project, used_up, [{"text": "1"}])
            send_round(client, project, used_up, [{"text": "2"}])
        client.get(self._review_url(project, late))
        ZilPostReview.objects.filter(issue=late).update(started_at=timezone.now() - timedelta(hours=73))

        def answer(issue):
            return client.post(
                f"/api/public/portal/{project.id}/posts/{issue.id}/drafts/", {"text": "x"}, format="json"
            )

        closed = {issue.name: answer(issue) for issue in (used_up, late, early)}
        assert {name: r.status_code for name, r in closed.items()} == {"Usado": 409, "Tarde": 409, "Temprano": 409}
        assert {name: r.json()["review"]["reason"] for name, r in closed.items()} == {
            "Usado": "rounds_used",
            "Tarde": "expired",
            "Temprano": "not_started",
        }
        assert client.get(self._review_url(project, early)).json()["review"]["open"] is False

    @pytest.mark.django_db
    def test_no_limits_when_the_brand_sets_none(self, kfc, cliente):
        project = kfc.project
        ZilClientPortal.objects.filter(project=project).update(change_rounds=0, change_hours=0)
        issue = item(project, "Reel", state_name=REVIEW_STATE)
        ZilPostReview.objects.create(issue=issue, project=project, started_at=timezone.now() - timedelta(days=90))
        with mock.patch(ACTIVITY):
            for text in ("1", "2", "3"):
                assert send_round(as_user(cliente), project, issue, [{"text": text}]).status_code == 201

        review = as_user(cliente).get(self._review_url(project, issue)).json()["review"]
        assert review == {"rounds": None, "used": 3, "left": None, "deadline": None, "open": True, "reason": None}

    @pytest.mark.django_db
    def test_the_marca_tab_sets_the_rounds_and_hours(self, kfc, create_user):
        project = kfc.project
        ProjectMember.objects.update_or_create(
            project=project, member=create_user, defaults={"workspace_id": project.workspace_id, "role": 20}
        )
        url = f"/api/workspaces/{project.workspace.slug}/projects/{project.id}/zil-portal/"

        saved = as_user(create_user).patch(url, {"change_rounds": 3, "change_hours": 48}, format="json")
        bad = [
            as_user(create_user).patch(url, body, format="json").status_code
            for body in (
                {"change_rounds": -1},
                {"change_rounds": 21},
                {"change_hours": "48"},
                {"change_hours": True},
                {},
            )
        ]

        assert saved.status_code == 200
        assert (saved.json()["change_rounds"], saved.json()["change_hours"]) == (3, 48)
        assert saved.json()["enabled"] is True  # the switch stays as it was
        assert bad == [400] * 5


@pytest.mark.contract
class TestWelcomeTour:
    @pytest.mark.django_db
    def test_a_client_sees_the_tour_once_and_its_end_is_kept(self, cliente):
        Profile.objects.get_or_create(user=cliente)
        client = as_user(cliente)

        before = client.get("/api/users/me/profile/").json()["is_tour_completed"]
        saved = client.patch("/api/users/me/profile/", {"is_tour_completed": True}, format="json")

        assert before is False
        assert saved.status_code == 200
        assert Profile.objects.get(user=cliente).is_tour_completed is True


@pytest.mark.contract
class TestVideoUploadCap:
    @pytest.mark.django_db
    def test_a_video_attachment_gets_the_video_cap_and_other_files_keep_theirs(self, kfc, create_user, settings):
        settings.FILE_SIZE_LIMIT = 5 * 1024 * 1024
        settings.VIDEO_FILE_SIZE_LIMIT = 95 * 1024 * 1024
        project = kfc.project
        ProjectMember.objects.update_or_create(
            project=project,
            member=create_user,
            defaults={"workspace_id": project.workspace_id, "role": 20, "is_active": True},
        )
        issue = item(project, "Reel")
        url = f"/api/assets/v2/workspaces/{project.workspace.slug}/projects/{project.id}/issues/{issue.id}/attachments/"

        with mock.patch("plane.app.views.issue.attachment.S3Storage") as storage:
            storage.return_value.generate_presigned_post.return_value = {"url": "x", "fields": {}}
            film = as_user(create_user).post(
                url, {"name": "reel.mp4", "type": "video/mp4", "size": 80 * 1024 * 1024}, format="json"
            )
            huge = as_user(create_user).post(
                url, {"name": "big.mp4", "type": "video/mp4", "size": 500 * 1024 * 1024}, format="json"
            )
            pdf = as_user(create_user).post(
                url, {"name": "brief.pdf", "type": "application/pdf", "size": 80 * 1024 * 1024}, format="json"
            )
        caps = [call.kwargs["file_size"] for call in storage.return_value.generate_presigned_post.call_args_list]

        assert [film.status_code, huge.status_code, pdf.status_code] == [200, 200, 200]
        assert caps == [80 * 1024 * 1024, 95 * 1024 * 1024, 5 * 1024 * 1024]
