# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from unittest import mock

import pytest
from django.utils import timezone
from rest_framework import status

from plane.authentication.utils.zil_provisioning import get_service_user
from plane.db.models import FileAsset, Issue, Page, Project, ProjectMember, ProjectPage, User, WorkspaceMember
from plane.utils.zil_client import ZilUnavailable, get_issue_erp_doc_targets

LEAD_ID = "0123456789abcdef01234567"
CLIENT_ID = "0123456789abcdef01234568"
ZIL_ENV = {"ZIL_BASE_URL": "http://zil.test", "ZIL_SERVICE_SECRET": "secret", "WEB_URL": "http://ops.test"}
TARGETS = [{"type": "Lead", "id": LEAD_ID, "name": "Joyas Esmeralda"}]


@pytest.fixture
def zil_env():
    with mock.patch.dict("os.environ", ZIL_ENV):
        yield


@pytest.fixture
def service_client(api_client, zil_env):
    api_client.credentials(HTTP_X_ZIL_SERVICE_KEY="secret")
    return api_client


@pytest.fixture
def project(session_client, workspace):
    response = session_client.post(
        f"/api/workspaces/{workspace.slug}/projects/",
        {"name": "Clients Project", "identifier": "CLP"},
        format="json",
    )
    assert response.status_code == status.HTTP_201_CREATED
    return Project.objects.get(pk=response.data["id"])


@pytest.fixture
def issue(workspace, project, create_user):
    return Issue.objects.create(workspace=workspace, project=project, name="Campaña", created_by=create_user)


@pytest.fixture
def attachment(workspace, project, issue):
    return FileAsset.objects.create(
        workspace=workspace,
        project=project,
        issue=issue,
        entity_type=FileAsset.EntityTypeContext.ISSUE_ATTACHMENT,
        attributes={"name": "brief.pdf", "type": "application/pdf", "size": 1234},
        asset="ws/brief.pdf",
        size=1234,
        is_uploaded=True,
    )


def _guest(api_client, workspace, project, role):
    user = User.objects.create(email=f"role{role}@zil.test", username=f"role{role}")
    WorkspaceMember.objects.create(workspace=workspace, member=user, role=role)
    ProjectMember.objects.create(workspace=workspace, project=project, member=user, role=role)
    api_client.force_authenticate(user=user)
    return api_client


@pytest.mark.contract
class TestZilSearch:
    @pytest.mark.django_db
    def test_requires_service_key(self, api_client, workspace, zil_env):
        response = api_client.get("/api/zil/sync/search/", {"workspace_slug": workspace.slug, "type": "issue"})
        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)
        api_client.credentials(HTTP_X_ZIL_SERVICE_KEY="wrong")
        response = api_client.get("/api/zil/sync/search/", {"workspace_slug": workspace.slug, "type": "issue"})
        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)

    @pytest.mark.django_db
    def test_unknown_workspace_is_404_and_bad_type_400(self, service_client, workspace):
        response = service_client.get("/api/zil/sync/search/", {"workspace_slug": "nope", "type": "issue"})
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.data == {"error": "not_found"}
        response = service_client.get("/api/zil/sync/search/", {"workspace_slug": workspace.slug, "type": "cycle"})
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.django_db
    def test_issues_match_name_key_and_sequence(self, service_client, workspace, project, issue, create_user):
        other = Issue.objects.create(workspace=workspace, project=project, name="Otra", created_by=create_user)
        Issue.objects.create(
            workspace=workspace, project=project, name="Campaña vieja", archived_at=timezone.now(), created_by=create_user
        )
        key = f"CLP-{issue.sequence_id}"

        by_name = service_client.get(
            "/api/zil/sync/search/", {"workspace_slug": workspace.slug, "type": "issue", "q": "campa"}
        )
        assert by_name.status_code == status.HTTP_200_OK
        assert by_name.data["results"] == [
            {
                "type": "issue",
                "id": str(issue.id),
                "name": "Campaña",
                "key": key,
                "project_name": "Clients Project",
                "url": f"http://ops.test/{workspace.slug}/browse/{key}/",
            }
        ]
        by_key = service_client.get(
            "/api/zil/sync/search/", {"workspace_slug": workspace.slug, "type": "issue", "q": f"clp-{other.sequence_id}"}
        )
        assert [r["id"] for r in by_key.data["results"]] == [str(other.id)]
        by_seq = service_client.get(
            "/api/zil/sync/search/", {"workspace_slug": workspace.slug, "type": "issue", "q": str(issue.sequence_id)}
        )
        assert str(issue.id) in [r["id"] for r in by_seq.data["results"]]

    @pytest.mark.django_db
    def test_limit_and_recency_order(self, service_client, workspace, project, issue, create_user):
        newer = Issue.objects.create(workspace=workspace, project=project, name="Nueva", created_by=create_user)
        response = service_client.get(
            "/api/zil/sync/search/", {"workspace_slug": workspace.slug, "type": "issue", "limit": 1}
        )
        assert [r["id"] for r in response.data["results"]] == [str(newer.id)]

    @pytest.mark.django_db
    def test_projects_exclude_archived(self, service_client, workspace, project):
        Project.objects.create(workspace=workspace, name="Old", identifier="OLD", archived_at=timezone.now())
        response = service_client.get("/api/zil/sync/search/", {"workspace_slug": workspace.slug, "type": "project"})
        assert response.data["results"] == [
            {
                "type": "project",
                "id": str(project.id),
                "name": "Clients Project",
                "key": "CLP",
                "project_name": "Clients Project",
                "url": f"http://ops.test/{workspace.slug}/projects/{project.id}/issues/",
            }
        ]

    @pytest.mark.django_db
    def test_pages_only_public_and_live(self, service_client, workspace, project, create_user):
        pages = {
            name: Page.objects.create(workspace=workspace, name=name, owned_by=create_user, **extra)
            for name, extra in (
                ("Brief", {"access": 0}),
                ("Private", {"access": 1}),
                ("Archived", {"access": 0, "archived_at": timezone.now()}),
            )
        }
        for page in pages.values():
            ProjectPage.objects.create(workspace=workspace, project=project, page=page)
        response = service_client.get("/api/zil/sync/search/", {"workspace_slug": workspace.slug, "type": "page"})
        brief = pages["Brief"]
        assert response.data["results"] == [
            {
                "type": "page",
                "id": str(brief.id),
                "name": "Brief",
                "key": "",
                "project_name": "Clients Project",
                "url": f"http://ops.test/{workspace.slug}/projects/{project.id}/pages/{brief.id}/",
            }
        ]


@pytest.mark.contract
class TestZilMemberships:
    @pytest.mark.django_db
    def test_requires_service_key(self, api_client, workspace, zil_env):
        response = api_client.get("/api/zil/sync/memberships/", {"slugs": workspace.slug})
        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)

    @pytest.mark.django_db
    def test_lists_human_members_per_slug(self, service_client, workspace, create_user, create_bot_user):
        inactive = User.objects.create(email="gone@zil.test", username="gone")
        WorkspaceMember.objects.create(workspace=workspace, member=inactive, role=15, is_active=False)
        WorkspaceMember.objects.create(workspace=workspace, member=create_bot_user, role=20)
        WorkspaceMember.objects.create(workspace=workspace, member=get_service_user(), role=20)

        response = service_client.get("/api/zil/sync/memberships/", {"slugs": f"{workspace.slug},missing"})
        assert response.status_code == status.HTTP_200_OK
        assert response.data["workspaces"]["missing"] == {"exists": False, "members": []}
        ws = response.data["workspaces"][workspace.slug]
        assert ws["exists"] is True
        assert sorted(ws["members"], key=lambda m: m["email"]) == sorted(
            [
                {"email": create_user.email, "role": 20, "is_active": True},
                {"email": "gone@zil.test", "role": 15, "is_active": False},
            ],
            key=lambda m: m["email"],
        )

    @pytest.mark.django_db
    def test_too_many_slugs_is_400(self, service_client):
        slugs = ",".join(f"ws-{i}" for i in range(201))
        assert service_client.get("/api/zil/sync/memberships/", {"slugs": slugs}).status_code == 400
        assert service_client.get("/api/zil/sync/memberships/").status_code == 400


@pytest.mark.contract
class TestZilIssueErpTargets:
    @pytest.mark.django_db
    def test_relays_doc_targets(self, session_client, issue, zil_env):
        with mock.patch(
            "plane.authentication.views.zil_sync.get_issue_erp_doc_targets", return_value=TARGETS
        ) as get_targets:
            response = session_client.get("/api/zil/issue-erp-targets/", {"issue_id": str(issue.id)})
        assert response.status_code == status.HTTP_200_OK
        get_targets.assert_called_once_with(str(issue.id))
        assert response.data == {"targets": TARGETS}

    @pytest.mark.django_db
    def test_non_member_is_404(self, api_client, issue, zil_env):
        outsider = User.objects.create(email="out@zil.test", username="out")
        api_client.force_authenticate(user=outsider)
        response = api_client.get("/api/zil/issue-erp-targets/", {"issue_id": str(issue.id)})
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.django_db
    def test_zil_down_is_502(self, session_client, issue, zil_env):
        with mock.patch(
            "plane.authentication.views.zil_sync.get_issue_erp_doc_targets", side_effect=ZilUnavailable
        ):
            response = session_client.get("/api/zil/issue-erp-targets/", {"issue_id": str(issue.id)})
        assert response.status_code == status.HTTP_502_BAD_GATEWAY

    def test_client_keeps_only_entities_with_documents(self, zil_env):
        links = [
            {"type": "Lead", "id": LEAD_ID, "name": "Joyas Esmeralda", "url": "http://zil.test/l"},
            {"type": "MgmtClient", "id": CLIENT_ID, "name": "Joyas", "url": "http://zil.test/c"},
            {"type": "TimeProject", "id": "0123456789abcdef01234569", "name": "SEO", "url": "http://zil.test/p"},
        ]
        resp = mock.Mock(status_code=200, json=lambda: {"links": links})
        with mock.patch("plane.utils.zil_client.requests.get", return_value=resp) as get:
            targets = get_issue_erp_doc_targets("issue-1")
        assert get.call_args.args[0] == "http://zil.test/api/zil/entity-meta"
        assert get.call_args.kwargs["params"] == {"plane_entity_id": "issue-1"}
        assert targets == [
            {"type": "Lead", "id": LEAD_ID, "name": "Joyas Esmeralda"},
            {"type": "MgmtClient", "id": CLIENT_ID, "name": "Joyas"},
        ]


@pytest.mark.contract
class TestZilIssueErpDocs:
    def _body(self, issue, asset_id, target_type="Lead", target_id=LEAD_ID):
        return {"issue_id": str(issue.id), "asset_id": str(asset_id), "target_type": target_type, "target_id": target_id}

    @pytest.mark.django_db
    def test_relays_the_attachment_to_zil(self, session_client, workspace, issue, attachment, create_user, zil_env):
        with mock.patch("plane.authentication.views.zil_sync.save_issue_doc_to_zil", return_value=True) as save:
            response = session_client.post("/api/zil/issue-erp-docs/", self._body(issue, attachment.id), format="json")
        assert response.status_code == status.HTTP_200_OK
        assert response.data == {"success": True}
        save.assert_called_once_with(
            {
                "leadsEntityType": "Lead",
                "leadsEntityId": LEAD_ID,
                "workspace_slug": workspace.slug,
                "plane_issue_id": str(issue.id),
                "asset_id": str(attachment.id),
                "name": "brief.pdf",
                "type": "application/pdf",
                "size": 1234,
                "actor_email": create_user.email,
            }
        )

    @pytest.mark.django_db
    def test_erp_404_is_mapped(self, session_client, issue, attachment, zil_env):
        with mock.patch("plane.authentication.views.zil_sync.save_issue_doc_to_zil", return_value=None):
            response = session_client.post(
                "/api/zil/issue-erp-docs/", self._body(issue, attachment.id, "MgmtClient", CLIENT_ID), format="json"
            )
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.data == {"error": "erp_entity_not_found"}

    @pytest.mark.django_db
    def test_zil_down_is_502(self, session_client, issue, attachment, zil_env):
        with mock.patch("plane.authentication.views.zil_sync.save_issue_doc_to_zil", side_effect=ZilUnavailable):
            response = session_client.post("/api/zil/issue-erp-docs/", self._body(issue, attachment.id), format="json")
        assert response.status_code == status.HTTP_502_BAD_GATEWAY
        assert response.data == {"error": "zil_unavailable"}

    @pytest.mark.django_db
    def test_asset_of_another_issue_is_rejected(
        self, session_client, workspace, project, issue, attachment, create_user, zil_env
    ):
        other = Issue.objects.create(workspace=workspace, project=project, name="Otra", created_by=create_user)
        with mock.patch("plane.authentication.views.zil_sync.save_issue_doc_to_zil") as save:
            response = session_client.post("/api/zil/issue-erp-docs/", self._body(other, attachment.id), format="json")
            attachment.is_uploaded = False
            attachment.save(update_fields=["is_uploaded"])
            pending = session_client.post("/api/zil/issue-erp-docs/", self._body(issue, attachment.id), format="json")
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert pending.status_code == status.HTTP_404_NOT_FOUND
        save.assert_not_called()

    @pytest.mark.django_db
    def test_guest_and_non_member_are_404(self, api_client, workspace, project, issue, attachment, zil_env):
        client = _guest(api_client, workspace, project, role=5)
        with mock.patch("plane.authentication.views.zil_sync.save_issue_doc_to_zil") as save:
            as_guest = client.post("/api/zil/issue-erp-docs/", self._body(issue, attachment.id), format="json")
            client.force_authenticate(user=User.objects.create(email="out@zil.test", username="out"))
            as_outsider = client.post("/api/zil/issue-erp-docs/", self._body(issue, attachment.id), format="json")
        assert as_guest.status_code == status.HTTP_404_NOT_FOUND
        assert as_outsider.status_code == status.HTTP_404_NOT_FOUND
        save.assert_not_called()

    @pytest.mark.django_db
    def test_invalid_target_is_400(self, session_client, issue, attachment, zil_env):
        for target_type, target_id in (("TimeProject", LEAD_ID), ("Lead", "nope")):
            response = session_client.post(
                "/api/zil/issue-erp-docs/", self._body(issue, attachment.id, target_type, target_id), format="json"
            )
            assert response.status_code == status.HTTP_400_BAD_REQUEST
