# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""What Ops relays to Zil for a client folder: who is asked, who may ask, and what comes back."""

from unittest import mock

import pytest
import requests
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework import status
from rest_framework.test import APIClient

from plane.db.models import Page, PageZilClientLink, ProjectMember, User, WorkspaceMember
from plane.utils import zil_client
from plane.utils.zil_client import ZilUnavailable, zil_client_relay

CLIENT_ID = "0123456789abcdef01234567"
OTHER_CLIENT_ID = "0123456789abcdef01234568"
ASSET_ID = "0123456789abcdef01234569"
RELAY = "plane.app.views.page.zil_client.zil_client_relay"
ZIL_ENV = {"ZIL_BASE_URL": "http://zil.test", "ZIL_SERVICE_SECRET": "secret"}
MB = 1024 * 1024


@pytest.fixture(autouse=True)
def no_background_tasks():
    with (
        mock.patch("plane.app.views.page.base.page_transaction.delay"),
        mock.patch("plane.app.views.page.base.recent_visited_task.delay"),
        mock.patch("plane.app.views.page.base.refresh_zil_client_link.delay"),
        mock.patch.dict("os.environ", ZIL_ENV),
    ):
        yield


@pytest.fixture
def project(session_client, workspace):
    response = session_client.post(
        f"/api/workspaces/{workspace.slug}/projects/",
        {"name": "Relay Project", "identifier": "RLY"},
        format="json",
    )
    assert response.status_code == status.HTTP_201_CREATED
    return response.data


def pages_url(workspace, project, suffix=""):
    return f"/api/workspaces/{workspace.slug}/projects/{project['id']}/pages/{suffix}"


def zil_url(workspace, project, page_id, suffix=""):
    return pages_url(workspace, project, f"{page_id}/zil-client/{suffix}")


def create_folder(client, workspace, project, **data):
    response = client.post(pages_url(workspace, project), {"name": "Nike", "kind": "folder", **data}, format="json")
    assert response.status_code == status.HTTP_201_CREATED, response.data
    return response.data


def link_folder(workspace, project, folder, client_id=CLIENT_ID, user=None):
    return PageZilClientLink.objects.create(
        workspace=workspace,
        project_id=project["id"],
        page_id=folder["id"],
        zil_client_id=client_id,
        alias="Nike",
        created_by=user,
    )


@pytest.fixture
def folder(session_client, workspace, project):
    created = create_folder(session_client, workspace, project)
    link_folder(workspace, project, created)
    return created


def member_client(workspace, project, email, project_role):
    """A signed-in person who belongs to the project with `project_role`."""
    user = User.objects.create(email=email, username=email, first_name="Other", last_name="Person")
    WorkspaceMember.objects.create(workspace=workspace, member=user, role=15)
    ProjectMember.objects.create(project_id=project["id"], workspace=workspace, member=user, role=project_role)
    api = APIClient()
    api.force_authenticate(user=user)
    return api, user


def relay_calls(client, workspace, project, page_id):
    """Every relayed call a folder offers: (name, send(client), expected Zil method, expected subpath)."""
    base = zil_url(workspace, project, page_id)
    return [
        ("profile", lambda c: c.get(base + "profile/"), "GET", "/profile"),
        (
            "asset create",
            lambda c: c.post(base + "assets/", {"kind": "link", "label": "x"}, format="json"),
            "POST",
            "/assets",
        ),
        (
            "asset update",
            lambda c: c.patch(base + f"assets/{ASSET_ID}/", {"label": "y"}, format="json"),
            "PATCH",
            f"/assets/{ASSET_ID}",
        ),
        ("asset delete", lambda c: c.delete(base + f"assets/{ASSET_ID}/"), "DELETE", f"/assets/{ASSET_ID}"),
        ("drive", lambda c: c.get(base + f"assets/{ASSET_ID}/drive/"), "GET", f"/assets/{ASSET_ID}/drive"),
        (
            "brand upload",
            lambda c: c.post(
                base + "brand-files/",
                {"file": SimpleUploadedFile("logo.png", b"png", content_type="image/png")},
                format="multipart",
            ),
            "POST",
            "/brand-files",
        ),
        ("brand open", lambda c: c.get(base + f"brand-files/{ASSET_ID}/"), "GET", f"/brand-files/{ASSET_ID}/url"),
        ("brand delete", lambda c: c.delete(base + f"brand-files/{ASSET_ID}/"), "DELETE", f"/brand-files/{ASSET_ID}"),
    ]


def fake_zil_response(status_code, body=None, json_error=False):
    response = mock.Mock(spec=requests.Response)
    response.status_code = status_code
    if json_error:
        response.json.side_effect = ValueError("not json")
    else:
        response.json.return_value = body if body is not None else {}
    return response


@pytest.mark.contract
class TestLinkPickerScoping:
    @pytest.mark.django_db
    def test_picker_asks_zil_for_what_this_person_may_pick(self, session_client, workspace, project, create_user):
        listing = fake_zil_response(200, {"clients": [{"id": CLIENT_ID, "alias": "Nike"}]})
        with mock.patch("plane.utils.zil_client.requests.get", return_value=listing) as get:
            response = session_client.get(
                f"/api/workspaces/{workspace.slug}/projects/{project['id']}/zil-clients/", {"q": "ni"}
            )
        assert response.status_code == status.HTTP_200_OK
        assert response.data["results"][0]["id"] == CLIENT_ID
        assert get.call_args.args[0] == "http://zil.test/api/sso/clients"
        assert get.call_args.kwargs["params"] == {
            "workspaceSlug": workspace.slug,
            "q": "ni",
            "limit": 20,
            "actor": create_user.email,
        }

    @pytest.mark.django_db
    def test_picker_marks_the_client_whose_folder_exists(self, session_client, workspace, project, folder):
        listing = fake_zil_response(200, {"clients": [{"id": CLIENT_ID}, {"id": OTHER_CLIENT_ID}]})
        with mock.patch("plane.utils.zil_client.requests.get", return_value=listing):
            response = session_client.get(f"/api/workspaces/{workspace.slug}/projects/{project['id']}/zil-clients/")
        by_id = {c["id"]: c["linkedPageId"] for c in response.data["results"]}
        assert str(by_id[CLIENT_ID]) == str(folder["id"])
        assert by_id[OTHER_CLIENT_ID] is None

    @pytest.mark.django_db
    def test_picker_is_a_502_when_zil_refuses_the_actor(self, session_client, workspace, project):
        with mock.patch("plane.utils.zil_client.requests.get", return_value=fake_zil_response(400)):
            response = session_client.get(f"/api/workspaces/{workspace.slug}/projects/{project['id']}/zil-clients/")
        assert response.status_code == status.HTTP_502_BAD_GATEWAY
        assert response.data == {"enabled": True, "error": "ZIL_UNAVAILABLE"}

    @pytest.mark.django_db
    def test_a_guest_cannot_open_the_picker(self, workspace, project):
        guest, _ = member_client(workspace, project, "guest@plane.so", project_role=5)
        with mock.patch("plane.utils.zil_client.requests.get") as get:
            response = guest.get(f"/api/workspaces/{workspace.slug}/projects/{project['id']}/zil-clients/")
        assert response.status_code == status.HTTP_403_FORBIDDEN
        get.assert_not_called()


@pytest.mark.contract
class TestFolderLink:
    @pytest.mark.django_db
    def test_a_folder_moves_to_another_client(self, session_client, workspace, project, folder):
        other = {"id": OTHER_CLIENT_ID, "alias": "Adidas", "companyName": "Adidas SA", "lifecycleStatus": "active"}
        with mock.patch("plane.app.views.page.zil_client.get_zil_client", return_value=other):
            response = session_client.post(
                zil_url(workspace, project, folder["id"]), {"zil_client_id": OTHER_CLIENT_ID}, format="json"
            )
        assert response.status_code == status.HTTP_200_OK
        assert response.data["alias"] == "Adidas"
        assert list(PageZilClientLink.objects.values_list("zil_client_id", flat=True)) == [OTHER_CLIENT_ID]

    @pytest.mark.django_db
    def test_zil_down_is_a_502_and_leaves_the_link_alone(self, session_client, workspace, project, folder):
        with mock.patch("plane.app.views.page.zil_client.get_zil_client", side_effect=ZilUnavailable):
            response = session_client.post(
                zil_url(workspace, project, folder["id"]), {"zil_client_id": OTHER_CLIENT_ID}, format="json"
            )
        assert response.status_code == status.HTTP_502_BAD_GATEWAY
        assert PageZilClientLink.objects.get(page_id=folder["id"]).zil_client_id == CLIENT_ID

    @pytest.mark.django_db
    def test_an_archived_folder_cannot_be_linked(self, session_client, workspace, project):
        archived = create_folder(session_client, workspace, project, name="Old")
        assert session_client.post(pages_url(workspace, project, f"{archived['id']}/archive/")).status_code == 200
        with mock.patch("plane.app.views.page.zil_client.get_zil_client") as get_client:
            response = session_client.post(
                zil_url(workspace, project, archived["id"]), {"zil_client_id": CLIENT_ID}, format="json"
            )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["error_message"] == "PAGE_ARCHIVED"
        get_client.assert_not_called()


@pytest.mark.contract
class TestWhoMayRelay:
    @pytest.mark.django_db
    def test_a_project_member_is_relayed_as_themselves_not_as_the_folder_owner(self, workspace, project, folder):
        member, user = member_client(workspace, project, "member@plane.so", project_role=15)
        with mock.patch(RELAY, return_value=(200, {"profile": {"id": CLIENT_ID, "info": {}}})) as relay:
            response = member.get(zil_url(workspace, project, folder["id"], "profile/"))
        assert response.status_code == status.HTTP_200_OK
        relay.assert_called_once_with("GET", CLIENT_ID, "/profile", workspace.slug, user.email, json=None, files=None)

    @pytest.mark.django_db
    def test_a_guest_reaches_nothing_and_zil_is_never_called(self, session_client, workspace, project, folder):
        guest, _ = member_client(workspace, project, "guest@plane.so", project_role=5)
        with mock.patch(RELAY) as relay:
            for name, send, _, _ in relay_calls(guest, workspace, project, folder["id"]):
                response = send(guest)
                assert response.status_code == status.HTTP_403_FORBIDDEN, name
        relay.assert_not_called()

    @pytest.mark.django_db
    def test_someone_outside_the_project_reaches_nothing(self, workspace, project, folder):
        user = User.objects.create(email="outsider@plane.so", username="outsider")
        WorkspaceMember.objects.create(workspace=workspace, member=user, role=15)
        outsider = APIClient()
        outsider.force_authenticate(user=user)
        with mock.patch(RELAY) as relay:
            for name, send, _, _ in relay_calls(outsider, workspace, project, folder["id"]):
                assert send(outsider).status_code == status.HTTP_403_FORBIDDEN, name
        relay.assert_not_called()

    @pytest.mark.django_db
    def test_a_private_folder_of_someone_else_is_not_found_for_every_relayed_call(
        self, session_client, workspace, project
    ):
        private = create_folder(session_client, workspace, project, name="Secret", access=Page.PRIVATE_ACCESS)
        link_folder(workspace, project, private)
        member, _ = member_client(workspace, project, "member@plane.so", project_role=15)
        with mock.patch(RELAY) as relay:
            for name, send, _, _ in relay_calls(member, workspace, project, private["id"]):
                assert send(member).status_code == status.HTTP_404_NOT_FOUND, name
        relay.assert_not_called()

    @pytest.mark.django_db
    def test_the_owner_of_a_private_folder_still_reaches_it(self, session_client, workspace, project):
        private = create_folder(session_client, workspace, project, name="Mine", access=Page.PRIVATE_ACCESS)
        link_folder(workspace, project, private)
        with mock.patch(RELAY, return_value=(200, {"profile": {"id": CLIENT_ID, "info": {}}})):
            response = session_client.get(zil_url(workspace, project, private["id"], "profile/"))
        assert response.status_code == status.HTTP_200_OK

    @pytest.mark.django_db
    def test_a_folder_is_not_reachable_through_another_project(self, session_client, workspace, project, folder):
        other = session_client.post(
            f"/api/workspaces/{workspace.slug}/projects/", {"name": "Other", "identifier": "OTH"}, format="json"
        ).data
        with mock.patch(RELAY) as relay:
            response = session_client.get(zil_url(workspace, other, folder["id"], "profile/"))
        assert response.status_code == status.HTTP_404_NOT_FOUND
        relay.assert_not_called()

    @pytest.mark.django_db
    def test_a_plain_page_has_no_client_panel(self, session_client, workspace, project):
        page = session_client.post(pages_url(workspace, project), {"name": "Doc"}, format="json").data
        with mock.patch(RELAY) as relay:
            response = session_client.get(zil_url(workspace, project, page["id"], "profile/"))
        assert response.status_code == status.HTTP_404_NOT_FOUND
        relay.assert_not_called()

    @pytest.mark.django_db
    def test_a_folder_without_a_client_asks_zil_nothing(self, session_client, workspace, project):
        loose = create_folder(session_client, workspace, project, name="Loose")
        with mock.patch(RELAY) as relay:
            for name, send, _, _ in relay_calls(session_client, workspace, project, loose["id"]):
                response = send(session_client)
                assert response.status_code == status.HTTP_400_BAD_REQUEST, name
                assert response.data["error_message"] == "ZIL_CLIENT_NOT_LINKED", name
        relay.assert_not_called()

    @pytest.mark.django_db
    def test_a_deleted_link_is_no_link(self, session_client, workspace, project, folder):
        assert session_client.delete(zil_url(workspace, project, folder["id"])).status_code == 204
        with mock.patch(RELAY) as relay:
            response = session_client.get(zil_url(workspace, project, folder["id"], "profile/"))
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        relay.assert_not_called()

    @pytest.mark.django_db
    def test_with_zil_off_nothing_is_relayed(self, session_client, workspace, project, folder):
        with mock.patch.dict("os.environ", {"ZIL_BASE_URL": "", "ZIL_SERVICE_SECRET": ""}), mock.patch(RELAY) as relay:
            for name, send, _, _ in relay_calls(session_client, workspace, project, folder["id"]):
                assert send(session_client).status_code == status.HTTP_503_SERVICE_UNAVAILABLE, name
        relay.assert_not_called()

    @pytest.mark.django_db
    def test_an_id_that_is_not_an_object_id_never_reaches_a_zil_path(self, session_client, workspace, project, folder):
        base = zil_url(workspace, project, folder["id"])
        with mock.patch(RELAY) as relay:
            assert session_client.delete(base + "assets/..profile/").status_code == 400
            assert session_client.get(base + "assets/NOT-AN-ID/drive/").status_code == 400
            assert session_client.get(base + "brand-files/1234/").status_code == 400
        relay.assert_not_called()


@pytest.mark.contract
class TestWhatComesBack:
    @pytest.mark.django_db
    @pytest.mark.parametrize("zil_status", [400, 403, 404, 409, 413])
    def test_zil_refusals_keep_their_status_and_their_message_on_every_call(
        self, session_client, workspace, project, folder, zil_status
    ):
        with mock.patch(RELAY, return_value=(zil_status, {"message": "porque si"})):
            for name, send, _, _ in relay_calls(session_client, workspace, project, folder["id"]):
                response = send(session_client)
                assert response.status_code == zil_status, name
                assert response.data == {"error": "porque si"}, name

    @pytest.mark.django_db
    def test_a_refusal_without_a_message_still_says_something(self, session_client, workspace, project, folder):
        with mock.patch(RELAY, return_value=(413, {})):
            response = session_client.get(zil_url(workspace, project, folder["id"], "profile/"))
        assert response.status_code == 413
        assert response.data == {"error": "ZIL_ERROR"}

    @pytest.mark.django_db
    @pytest.mark.parametrize("zil_status", [401, 405, 422, 429])
    def test_what_zil_does_not_explain_is_a_502_never_a_500(
        self, session_client, workspace, project, folder, zil_status
    ):
        with mock.patch(RELAY, return_value=(zil_status, {"message": "x"})):
            for name, send, _, _ in relay_calls(session_client, workspace, project, folder["id"]):
                response = send(session_client)
                assert response.status_code == status.HTTP_502_BAD_GATEWAY, name
                assert response.data == {"error": "ZIL_UNAVAILABLE"}, name

    @pytest.mark.django_db
    def test_zil_unreachable_is_a_502_on_every_call(self, session_client, workspace, project, folder):
        with mock.patch(RELAY, side_effect=ZilUnavailable):
            for name, send, _, _ in relay_calls(session_client, workspace, project, folder["id"]):
                assert send(session_client).status_code == status.HTTP_502_BAD_GATEWAY, name

    @pytest.mark.django_db
    def test_every_call_goes_to_the_right_zil_path_as_the_signed_in_person(
        self, session_client, workspace, project, folder, create_user
    ):
        with mock.patch(RELAY, return_value=(200, {})) as relay:
            for name, send, method, subpath in relay_calls(session_client, workspace, project, folder["id"]):
                relay.reset_mock()
                send(session_client)
                args = relay.call_args.args
                assert args[:5] == (method, CLIENT_ID, subpath, workspace.slug, create_user.email), name

    @pytest.mark.django_db
    def test_an_answer_without_a_profile_or_url_is_not_an_empty_success(
        self, session_client, workspace, project, folder
    ):
        with mock.patch(RELAY, return_value=(200, {})):
            opened = session_client.get(zil_url(workspace, project, folder["id"], f"brand-files/{ASSET_ID}/"))
        assert opened.status_code == status.HTTP_502_BAD_GATEWAY

    @pytest.mark.django_db
    def test_asset_calls_forward_only_the_asset_fields(self, session_client, workspace, project, folder):
        with mock.patch(RELAY, return_value=(201, {"asset": {"id": ASSET_ID}})) as relay:
            created = session_client.post(
                zil_url(workspace, project, folder["id"], "assets/"),
                {"kind": "link", "label": "Sitio", "url": "https://nike.com", "business_unit": "x", "addedBy": "y"},
                format="json",
            )
        assert created.status_code == status.HTTP_201_CREATED
        assert relay.call_args.kwargs["json"] == {"kind": "link", "label": "Sitio", "url": "https://nike.com"}
        with mock.patch(RELAY, return_value=(200, {"asset": {"id": ASSET_ID}})) as relay:
            session_client.patch(
                zil_url(workspace, project, folder["id"], f"assets/{ASSET_ID}/"),
                {"kind": "vault", "label": "Nuevo"},
                format="json",
            )
        assert relay.call_args.kwargs["json"] == {"label": "Nuevo"}


@pytest.fixture
def default_body_limit(settings):
    """Ops' default FILE_SIZE_LIMIT (5 MB), which every request but a brand file upload keeps."""
    settings.DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * MB


def pdf_of(size):
    return b"%PDF-1.4\n" + b"a" * (size - 9)


def upload_brand_file(client, workspace, project, folder, content):
    upload = SimpleUploadedFile("manual.pdf", content, content_type="application/pdf")
    return client.post(zil_url(workspace, project, folder["id"], "brand-files/"), {"file": upload}, format="multipart")


@pytest.mark.contract
@pytest.mark.usefixtures("default_body_limit")
class TestBrandFileUpload:
    @pytest.mark.django_db
    @pytest.mark.parametrize("size", [19 * MB, 20 * MB], ids=["19 MB", "exactly 20 MB"])
    def test_a_file_up_to_20_mb_reaches_zil_whole_past_the_5_mb_body_limit(
        self, session_client, workspace, project, folder, size
    ):
        content = pdf_of(size)
        with mock.patch(RELAY, return_value=(201, {"file": {"id": ASSET_ID}})) as relay:
            response = upload_brand_file(session_client, workspace, project, folder, content)
        assert response.status_code == status.HTTP_201_CREATED, response.content[:200]
        assert relay.call_args.kwargs["files"]["file"][1] == content

    @pytest.mark.django_db
    def test_a_file_just_over_20_mb_is_a_413_that_says_the_limit_and_is_never_sent(
        self, session_client, workspace, project, folder
    ):
        with mock.patch(RELAY) as relay:
            response = upload_brand_file(session_client, workspace, project, folder, pdf_of(20 * MB + 1))
        assert response.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
        assert response.json() == {"error": "El archivo no puede pesar más de 20 MB."}
        relay.assert_not_called()

    @pytest.mark.django_db
    def test_a_21_mb_file_is_a_413_before_its_body_is_read(self, session_client, workspace, project, folder):
        with mock.patch(RELAY) as relay:
            response = upload_brand_file(session_client, workspace, project, folder, pdf_of(21 * MB))
        assert response.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
        assert response.json()["error"] == "REQUEST_BODY_TOO_LARGE"
        relay.assert_not_called()

    @pytest.mark.django_db
    @pytest.mark.parametrize(
        "suffix",
        ["zil-client/assets/", f"zil-client/brand-files/{ASSET_ID}/", "zil-client/brand-files/x/", ""],
        ids=["client asset", "a brand file's own url", "a path under brand-files", "page create"],
    )
    def test_every_other_request_keeps_the_5_mb_body_limit(self, session_client, workspace, project, folder, suffix):
        upload = SimpleUploadedFile("manual.pdf", pdf_of(6 * MB), content_type="application/pdf")
        with mock.patch(RELAY) as relay:
            response = session_client.post(
                pages_url(workspace, project, f"{folder['id']}/{suffix}" if suffix else ""),
                {"file": upload},
                format="multipart",
            )
        assert response.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
        assert response.json()["error"] == "REQUEST_BODY_TOO_LARGE"
        relay.assert_not_called()

    @pytest.mark.django_db
    @pytest.mark.parametrize(
        ("content_type", "format_"), [("application/json", "json"), ("application/x-www-form-urlencoded", None)]
    )
    def test_a_body_that_is_not_a_multipart_form_keeps_the_5_mb_body_limit_on_that_path(
        self, session_client, workspace, project, folder, content_type, format_
    ):
        # DRF parses these whole in memory, so they never get the brand file's 21 MB
        url = zil_url(workspace, project, folder["id"], "brand-files/")
        if format_:
            response = session_client.post(url, {"file": "a" * (6 * MB)}, format=format_)
        else:
            response = session_client.generic("POST", url, b"file=" + b"a" * (6 * MB), content_type=content_type)
        assert response.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
        assert response.json()["error"] == "REQUEST_BODY_TOO_LARGE"

    @pytest.mark.django_db
    @pytest.mark.parametrize("method", ["put", "patch", "delete"])
    def test_another_verb_keeps_the_5_mb_body_limit_on_that_path(
        self, session_client, workspace, project, folder, method
    ):
        upload = SimpleUploadedFile("manual.pdf", pdf_of(6 * MB), content_type="application/pdf")
        response = getattr(session_client, method)(
            zil_url(workspace, project, folder["id"], "brand-files/"), {"file": upload}, format="multipart"
        )
        assert response.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
        assert response.json()["error"] == "REQUEST_BODY_TOO_LARGE"

    @pytest.mark.django_db
    def test_a_form_field_past_the_5_mb_body_limit_is_a_413_not_a_server_error(
        self, session_client, workspace, project, folder
    ):
        # the file streams to disk, the form's other fields are held in memory and counted
        upload = SimpleUploadedFile("manual.pdf", pdf_of(1 * MB), content_type="application/pdf")
        with (
            mock.patch(RELAY) as relay,
            mock.patch("plane.app.views.base.capture_server_error") as capture_server_error,
        ):
            response = session_client.post(
                zil_url(workspace, project, folder["id"], "brand-files/"),
                {"file": upload, "note": "a" * (6 * MB)},
                format="multipart",
            )
        assert response.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
        assert response.json()["error"] == "REQUEST_BODY_TOO_LARGE"
        capture_server_error.assert_not_called()
        relay.assert_not_called()

    @pytest.mark.django_db
    def test_the_file_reaches_zil_whole(self, session_client, workspace, project, folder):
        content = bytes(range(256)) * 4096  # 1 MB with every byte value
        upload = SimpleUploadedFile("Logo diseño.png", content, content_type="image/png")
        with mock.patch(RELAY, return_value=(201, {"file": {"id": ASSET_ID}})) as relay:
            response = session_client.post(
                zil_url(workspace, project, folder["id"], "brand-files/"), {"file": upload}, format="multipart"
            )
        assert response.status_code == status.HTTP_201_CREATED
        name, sent, content_type = relay.call_args.kwargs["files"]["file"]
        assert (name, content_type) == ("Logo diseño.png", "image/png")
        assert sent == content

    @pytest.mark.django_db
    def test_no_file_is_a_400(self, session_client, workspace, project, folder):
        with mock.patch(RELAY) as relay:
            response = session_client.post(
                zil_url(workspace, project, folder["id"], "brand-files/"), {}, format="multipart"
            )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        relay.assert_not_called()

    @pytest.mark.django_db
    def test_a_file_without_a_type_is_sent_as_a_stream(self, session_client, workspace, project, folder):
        upload = SimpleUploadedFile("logo", b"abc", content_type="")
        with mock.patch(RELAY, return_value=(201, {"file": {"id": ASSET_ID}})) as relay:
            session_client.post(
                zil_url(workspace, project, folder["id"], "brand-files/"), {"file": upload}, format="multipart"
            )
        assert relay.call_args.kwargs["files"]["file"][2] == "application/octet-stream"


class TestRelayRequest:
    def relay(self, response=None, error=None, env=ZIL_ENV, **kwargs):
        with (
            mock.patch.dict("os.environ", env),
            mock.patch("plane.utils.zil_client.requests.request", return_value=response, side_effect=error) as request,
        ):
            outcome = zil_client_relay("GET", CLIENT_ID, "/profile", "nike-ws", "ana@zil.global", **kwargs)
        return outcome, request

    def test_it_asks_as_the_person_for_that_workspace_with_the_service_key(self):
        (status_code, body), request = self.relay(fake_zil_response(200, {"profile": {}}))
        assert (status_code, body) == (200, {"profile": {}})
        assert request.call_args.args == ("GET", f"http://zil.test/api/sso/clients/{CLIENT_ID}/profile")
        kwargs = request.call_args.kwargs
        assert kwargs["params"] == {"workspaceSlug": "nike-ws", "actor": "ana@zil.global"}
        assert kwargs["headers"] == {"X-Zil-Service-Key": "secret"}
        assert kwargs["timeout"] == zil_client.ZIL_RELAY_TIMEOUT_SECONDS

    def test_a_refusal_is_returned_not_raised(self):
        assert self.relay(fake_zil_response(403, {"message": "actor not in workspace"}))[0] == (
            403,
            {"message": "actor not in workspace"},
        )

    def test_a_refusal_with_a_page_instead_of_json_keeps_its_status(self):
        assert self.relay(fake_zil_response(413, json_error=True))[0] == (413, {})

    @pytest.mark.parametrize("zil_status", [500, 502, 503, 504])
    def test_a_zil_failure_is_unavailable(self, zil_status):
        with pytest.raises(ZilUnavailable):
            self.relay(fake_zil_response(zil_status, {"message": "internal error"}))

    @pytest.mark.parametrize("error", [requests.Timeout(), requests.ConnectionError(), OSError("dns")])
    def test_an_unreachable_zil_is_unavailable(self, error):
        with pytest.raises(ZilUnavailable):
            self.relay(error=error)

    def test_a_trailing_slash_in_the_base_url_does_not_double(self):
        _, request = self.relay(fake_zil_response(200, {}), env={**ZIL_ENV, "ZIL_BASE_URL": "http://zil.test/"})
        assert request.call_args.args[1] == f"http://zil.test/api/sso/clients/{CLIENT_ID}/profile"
