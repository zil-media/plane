# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from unittest import mock

import uuid

import pytest
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from plane.db.models import AgentPipelineConfig, FeatureRequest, User
from plane.license.models import Instance, InstanceAdmin
from plane.utils.agent_pipeline.features import request_spec

ZIL_ENV = {"ZIL_BASE_URL": "http://zil.test", "ZIL_SERVICE_SECRET": "secret"}
DRAFT = "No me deja mover el work item al ciclo nuevo y pierdo lo que cargué"
S = FeatureRequest.Status


@pytest.fixture(autouse=True)
def tasks():
    with (
        mock.patch("plane.bgtasks.agent_pipeline_task.fire_feature_routine_task.delay") as fire_feature,
        mock.patch("plane.bgtasks.agent_pipeline_task.send_support_email_task.delay") as email,
    ):
        yield {"fire_feature": fire_feature, "email": email}


def zil_answers(status_code=200, body=None):
    response = mock.Mock(status_code=status_code)
    response.json.return_value = body if body is not None else {}
    return mock.patch("plane.utils.zil_client.requests.post", return_value=response)


@pytest.mark.contract
class TestDraftReview:
    URL = "/api/support/draft-review/"

    @pytest.mark.django_db
    def test_relays_to_workspace_with_the_ops_kind(self, session_client):
        review = {"ready": False, "questions": [{"question": "¿Qué work item era?", "why": "Para buscarlo."}]}
        with mock.patch.dict("os.environ", ZIL_ENV), zil_answers(body={"success": True, "review": review}) as post:
            response = session_client.post(
                self.URL, {"kind": "bug", "text": DRAFT, "screen": "/ws/projects/"}, format="json"
            )
        assert response.status_code == status.HTTP_200_OK
        assert response.data == {"review": review}
        url, kwargs = post.call_args[0][0], post.call_args[1]
        assert url == "http://zil.test/api/zil/draft-review"
        assert kwargs["json"] == {"kind": "ops_bug", "title": "", "text": DRAFT, "screen": "/ws/projects/"}
        assert kwargs["headers"] == {"X-Zil-Service-Key": "secret"}

    @pytest.mark.django_db
    def test_short_draft_is_not_sent(self, session_client):
        with mock.patch.dict("os.environ", ZIL_ENV), zil_answers() as post:
            draft = {"kind": "feature", "title": "Exportar", "text": "a"}
            response = session_client.post(self.URL, draft, format="json")
        assert response.data == {"review": None}
        post.assert_not_called()

    @pytest.mark.django_db
    def test_without_zil_there_is_no_review(self, session_client):
        with mock.patch.dict("os.environ", {"ZIL_BASE_URL": "", "ZIL_SERVICE_SECRET": ""}), zil_answers() as post:
            response = session_client.post(self.URL, {"kind": "bug", "text": DRAFT}, format="json")
        assert response.data == {"review": None}
        post.assert_not_called()

    @pytest.mark.django_db
    def test_zil_failing_is_no_review_not_an_error(self, session_client):
        with mock.patch.dict("os.environ", ZIL_ENV), zil_answers(status_code=502):
            response = session_client.post(self.URL, {"kind": "bug", "text": DRAFT}, format="json")
        assert response.status_code == status.HTTP_200_OK
        assert response.data == {"review": None}

        with (
            mock.patch.dict("os.environ", ZIL_ENV),
            mock.patch("plane.utils.zil_client.requests.post", side_effect=ConnectionError("down")),
        ):
            response = session_client.post(self.URL, {"kind": "bug", "text": DRAFT}, format="json")
        assert response.data == {"review": None}

    @pytest.mark.django_db
    def test_unknown_kind_is_rejected(self, session_client):
        response = session_client.post(self.URL, {"kind": "dev_request", "text": DRAFT}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.contract
class TestAnsweringTheAgent:
    @pytest.fixture
    def asked(self, create_user):
        return FeatureRequest.objects.create(
            requested_by=create_user, title="Exportar", problem="No puedo exportar los work items", status=S.NEEDS_INFO
        )

    def answer(self, client, feature):
        return client.post(f"/api/support/feature-requests/{feature.id}/comments/", {"text": "CSV"}, format="json")

    @pytest.mark.django_db
    def test_says_when_the_analysis_restarted(self, session_client, asked, tasks):
        config = AgentPipelineConfig.get()
        config.feature_agent_enabled = True
        config.save()

        response = self.answer(session_client, asked)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["respec"] == {"queued": True, "reason": "queued"}
        assert response.data["status"] == "spec_running"
        tasks["fire_feature"].assert_called_once()

    @pytest.mark.django_db
    def test_says_when_it_did_not(self, session_client, asked, tasks):
        response = self.answer(session_client, asked)

        assert response.data["respec"] == {"queued": False, "reason": "disabled"}
        asked.refresh_from_db()
        assert asked.comments[-1]["text"] == "CSV"
        assert asked.status == S.NEEDS_INFO
        tasks["fire_feature"].assert_not_called()

    @pytest.mark.django_db
    def test_a_plain_comment_carries_no_respec(self, session_client, create_user):
        feature = FeatureRequest.objects.create(
            requested_by=create_user, title="Exportar", problem="No puedo exportar los work items", status=S.BUILDING
        )
        response = self.answer(session_client, feature)
        assert "respec" not in response.data


@pytest.fixture
def agent_on(db):
    config = AgentPipelineConfig.get()
    config.feature_agent_enabled = True
    config.save()
    return config


@pytest.fixture
def admin_client(db):
    instance = Instance.objects.create(
        instance_name="Test Instance",
        instance_id=str(uuid.uuid4()),
        current_version="1.0.0",
        domain="http://localhost:8000",
        last_checked_at=timezone.now(),
        is_setup_done=True,
    )
    admin = User.objects.create(email="owner@zil.global", username=uuid.uuid4().hex, is_active=True)
    InstanceAdmin.objects.create(instance=instance, user=admin, role=20)
    client = APIClient()
    client.force_authenticate(user=admin)
    return client


def own_feature(user, **fields):
    return FeatureRequest.objects.create(
        requested_by=user, title="Exportar", problem="No puedo exportar los work items", **fields
    )


@pytest.mark.contract
class TestRedoingTheAnalysis:
    def respec(self, client, feature):
        return client.post(f"/api/support/feature-requests/{feature.id}/respec/", format="json")

    @pytest.mark.django_db
    @pytest.mark.parametrize("state", [S.REJECTED, S.MERGED, S.BUILDING, S.ON_HOLD, S.SPEC_RUNNING])
    def test_requester_cannot_undo_a_decision_or_a_running_job(
        self, session_client, create_user, agent_on, tasks, state
    ):
        feature = own_feature(create_user, status=state)
        assert self.respec(session_client, feature).status_code == status.HTTP_409_CONFLICT
        feature.refresh_from_db()
        assert feature.status == state
        tasks["fire_feature"].assert_not_called()

    @pytest.mark.django_db
    def test_admin_resumes_a_paused_one_through_a_new_analysis(self, admin_client, create_user, agent_on, tasks):
        feature = own_feature(create_user, status=S.ON_HOLD)
        response = self.respec(admin_client, feature)
        assert response.status_code == status.HTTP_200_OK
        assert response.data["queued"] is True
        tasks["fire_feature"].assert_called_once()

    @pytest.mark.django_db
    def test_admin_cannot_pull_an_item_off_its_build(self, admin_client, create_user, agent_on, tasks):
        feature = own_feature(create_user, status=S.BUILDING)
        assert self.respec(admin_client, feature).status_code == status.HTTP_409_CONFLICT
        tasks["fire_feature"].assert_not_called()

    @pytest.mark.django_db
    def test_a_second_run_of_the_same_spec_is_refused(self, create_user, agent_on, tasks):
        feature = own_feature(create_user, status=S.NEEDS_INFO)
        assert request_spec(feature, "primera", force=True) == (True, "queued")
        stale = FeatureRequest.objects.get(id=feature.id)
        stale.status = S.NEEDS_INFO  # a copy read before the first run started
        assert request_spec(stale, "segunda", force=True) == (False, "status spec_running")
        tasks["fire_feature"].assert_called_once()
        feature.refresh_from_db()
        assert feature.spec_runs == 1

    @pytest.mark.django_db
    def test_a_decision_taken_meanwhile_wins_over_a_stale_copy(self, create_user, agent_on, tasks):
        feature = own_feature(create_user, status=S.NEEDS_INFO)
        FeatureRequest.objects.filter(id=feature.id).update(status=S.APPROVED)
        assert request_spec(feature, "respondió", force=True) == (False, "status approved")
        feature.refresh_from_db()
        assert feature.status == S.APPROVED

    @pytest.mark.django_db
    def test_force_only_lifts_the_run_cap(self, create_user, agent_on, tasks):
        capped = own_feature(create_user, status=S.SPEC_READY, spec_runs=3)
        assert request_spec(capped, "auto") == (False, "spec run limit")
        assert request_spec(capped, "a mano", force=True) == (True, "queued")

    @pytest.mark.django_db
    def test_approving_says_whether_the_build_started(self, admin_client, create_user, agent_on, tasks):
        busy = own_feature(create_user, status=S.BUILDING)
        ready = own_feature(create_user, status=S.SPEC_READY, flag_key="exportTasks")
        response = admin_client.post(f"/api/support/feature-requests/{ready.id}/approve/", {}, format="json")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["build"] == {"fired": False, "reason": "another build in flight"}
        assert response.data["status"] == "approved"

        busy.status = S.MERGED
        busy.save()
        response = admin_client.post(f"/api/support/feature-requests/{ready.id}/rebuild/", {}, format="json")
        assert response.data["build"]["fired"] is True
