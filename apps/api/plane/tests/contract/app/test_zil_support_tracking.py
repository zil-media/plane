# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import uuid
from unittest import mock

import pytest
from django.utils import timezone
from rest_framework import status

from plane.db.models import AgentFeatureFlag, BugReport, FeatureRequest, User, Workspace
from plane.license.models import Instance, InstanceAdmin

URL = "/api/zil/sync/support-tracking/"
ZIL_ENV = {"ZIL_SERVICE_SECRET": "secret"}
S = FeatureRequest.Status


@pytest.fixture
def service_client(api_client, settings):
    settings.WEB_URL = "http://ops.test"
    with mock.patch.dict("os.environ", ZIL_ENV):
        api_client.credentials(HTTP_X_ZIL_SERVICE_KEY="secret")
        yield api_client


@pytest.fixture
def instance(db):
    return Instance.objects.create(
        instance_name="Test Instance",
        instance_id=str(uuid.uuid4()),
        current_version="1.0.0",
        domain="http://localhost:8000",
        last_checked_at=timezone.now(),
        is_setup_done=True,
    )


@pytest.fixture
def other_user(db):
    return User.objects.create(email="otra@zil.global", username=uuid.uuid4().hex, is_active=True)


def feature(user, workspace=None, **fields):
    return FeatureRequest.objects.create(
        requested_by=user, workspace=workspace, title="Exportar tareas", problem="No puedo exportar", **fields
    )


def bug(user, **fields):
    fields.setdefault("description", "Quiero un filtro por cliente")
    return BugReport.objects.create(reported_by=user, **fields)


def ids(items):
    return {item["id"] for item in items}


@pytest.mark.contract
class TestZilSupportTracking:
    @pytest.mark.django_db
    def test_requires_service_key(self, api_client, create_user):
        with mock.patch.dict("os.environ", ZIL_ENV):
            response = api_client.get(URL, {"email": create_user.email})
        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)

    @pytest.mark.django_db
    def test_rejects_a_missing_or_malformed_email(self, service_client):
        assert service_client.get(URL).status_code == status.HTTP_400_BAD_REQUEST
        assert service_client.get(URL, {"email": "nadie"}).status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.django_db
    def test_unknown_person_gets_empty_lists(self, service_client):
        response = service_client.get(URL, {"email": "no-usa-ops@zil.global"})
        assert response.status_code == status.HTTP_200_OK
        assert response.data == {"is_admin": False, "features": [], "bugs": []}

    @pytest.mark.django_db
    def test_member_sees_own_suggestions_only(self, service_client, create_user, workspace, other_user, instance):
        question = {"at": "2026-10-01T10:00:00+00:00", "author_name": "", "role": "agent", "text": "- ¿Qué formato?"}
        mine = feature(create_user, workspace, status=S.NEEDS_INFO, comments=[question])
        theirs = feature(other_user, status=S.SPEC_READY)
        suggestion = bug(create_user, severity=BugReport.Severity.SUGERENCIA, workspace=workspace)
        annoying = bug(create_user, severity=BugReport.Severity.MOLESTO)
        bug(create_user, severity=BugReport.Severity.SUGERENCIA, workspace_bug_id="0123456789abcdef01234567")
        bug(create_user, severity=BugReport.Severity.SUGERENCIA, status=BugReport.Status.ARCHIVED)
        bug(other_user, severity=BugReport.Severity.SUGERENCIA)

        response = service_client.get(URL, {"email": create_user.email.upper()})

        assert response.status_code == status.HTTP_200_OK
        assert response.data["is_admin"] is False
        assert ids(response.data["features"]) == {str(mine.id)}
        assert str(theirs.id) not in ids(response.data["features"])
        item = response.data["features"][0]
        assert item["status"] == "needs_info"
        assert item["problem"] == "No puedo exportar"
        assert item["comments"] == [
            {"author_name": "", "role": "agent", "text": "- ¿Qué formato?", "at": "2026-10-01T10:00:00+00:00"}
        ]
        assert item["url"] == f"http://ops.test/{workspace.slug}/support?feature={mine.id}"
        assert ids(response.data["bugs"]) == {str(suggestion.id), str(annoying.id)}
        by_id = {b["id"]: b for b in response.data["bugs"]}
        assert by_id[str(suggestion.id)]["url"] == f"http://ops.test/{workspace.slug}/support?bug={suggestion.id}"
        assert "admin_notes" not in by_id[str(suggestion.id)] and "blocked_reason" not in by_id[str(suggestion.id)]

    @pytest.mark.django_db
    def test_item_without_workspace_opens_through_one_of_the_viewers(
        self, service_client, create_user, workspace, instance
    ):
        orphan = feature(create_user)
        response = service_client.get(URL, {"email": create_user.email})
        assert response.data["features"][0]["url"] == f"http://ops.test/{workspace.slug}/support?feature={orphan.id}"

    @pytest.mark.django_db
    def test_admin_also_sees_what_waits_on_an_admin(self, service_client, create_user, other_user, instance):
        InstanceAdmin.objects.create(instance=instance, user=create_user, role=20)
        ready = feature(other_user, status=S.SPEC_READY, spec={"blast_radius": "low", "generated_at": "2026-10-02"})
        stuck = feature(other_user, status=S.BUILDING, build={"blocked_at": "2026-10-03T00:00:00+00:00"})
        feature(other_user, status=S.BUILDING, build={"blocked_at": None})
        feature(other_user, status=S.APPROVED)
        shipped = feature(
            create_user,
            status=S.MERGED,
            flag_key="exportTasks",
            approval={"by": "auto", "at": "2026-10-01T00:00:00+00:00"},
        )
        enabled_at = timezone.now()
        AgentFeatureFlag.objects.create(key="exportTasks", enabled=True, feature=shipped, enabled_at=enabled_at)

        response = service_client.get(URL, {"email": create_user.email})

        assert response.data["is_admin"] is True
        assert ids(response.data["features"]) == {str(ready.id), str(stuck.id), str(shipped.id)}
        by_id = {f["id"]: f for f in response.data["features"]}
        assert by_id[str(ready.id)]["spec"]["blast_radius"] == "low"
        assert by_id[str(stuck.id)]["build"]["blocked_at"] == "2026-10-03T00:00:00+00:00"
        assert by_id[str(shipped.id)]["approval"]["auto"] is True
        assert by_id[str(shipped.id)]["flag_enabled_at"] == enabled_at.isoformat()

    @pytest.mark.django_db
    def test_item_in_a_workspace_the_viewer_is_not_in_opens_through_theirs(
        self, service_client, create_user, workspace, other_user, instance
    ):
        InstanceAdmin.objects.create(instance=instance, user=create_user, role=20)
        elsewhere = Workspace.objects.create(name="Otra", owner=other_user, slug="otra-unidad")
        ready = feature(other_user, elsewhere, status=S.SPEC_READY)
        response = service_client.get(URL, {"email": create_user.email})
        assert response.data["features"][0]["url"] == f"http://ops.test/{workspace.slug}/support?feature={ready.id}"

    @pytest.mark.django_db
    def test_the_report_goes_whole(self, service_client, create_user, instance):
        long_text = "Quiero filtrar por cliente. " * 40
        bug(create_user, severity=BugReport.Severity.SUGERENCIA, description=long_text)
        response = service_client.get(URL, {"email": create_user.email})
        assert response.data["bugs"][0]["description"] == long_text

    @pytest.mark.django_db
    def test_board_polls_are_not_anon_throttled(self, service_client, create_user):
        for _ in range(35):
            assert service_client.get(URL, {"email": create_user.email}).status_code == status.HTTP_200_OK
