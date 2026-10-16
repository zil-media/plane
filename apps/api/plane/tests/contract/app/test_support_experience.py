# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from unittest import mock

import pytest
from rest_framework import status

from plane.db.models import AgentPipelineConfig, FeatureRequest

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
