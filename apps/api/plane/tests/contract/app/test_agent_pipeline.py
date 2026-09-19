# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import uuid
from unittest import mock

import pytest
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from plane.db.models import AgentFeatureFlag, AgentPipelineConfig, BugReport, FeatureRequest, User
from plane.license.models import Instance, InstanceAdmin
from plane.utils.agent_pipeline.bugs import classify_urgency

BUG_KEY = "b" * 64
FEATURE_KEY = "f" * 64


@pytest.fixture(autouse=True)
def tasks():
    with (
        mock.patch("plane.bgtasks.agent_pipeline_task.fire_bug_routine_task.delay") as fire_bug,
        mock.patch("plane.bgtasks.agent_pipeline_task.fire_feature_routine_task.delay") as fire_feature,
        mock.patch("plane.bgtasks.agent_pipeline_task.send_support_email_task.delay") as email,
    ):
        yield {"fire_bug": fire_bug, "fire_feature": fire_feature, "email": email}


@pytest.fixture
def agent_user(db):
    return User.objects.create(email="agent@zil.global", username=uuid.uuid4().hex, is_active=True)


@pytest.fixture(autouse=True)
def agent_env(monkeypatch, agent_user):
    monkeypatch.setenv("OPS_BUG_AGENT_API_KEY", BUG_KEY)
    monkeypatch.setenv("OPS_FEATURE_AGENT_API_KEY", FEATURE_KEY)
    monkeypatch.setenv("AGENT_ADMIN_EMAIL", agent_user.email)


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
def admin_client(instance):
    admin = User.objects.create(email="owner@zil.global", username=uuid.uuid4().hex, is_active=True)
    InstanceAdmin.objects.create(instance=instance, user=admin, role=20)
    client = APIClient()
    client.force_authenticate(user=admin)
    return client


@pytest.fixture
def bug_agent():
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {BUG_KEY}")
    return client


@pytest.fixture
def feature_agent():
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {FEATURE_KEY}")
    return client


@pytest.fixture
def feature_agent_enabled(db):
    config = AgentPipelineConfig.get()
    config.feature_agent_enabled = True
    config.save()
    return config


def report_bug(client, **data):
    response = client.post("/api/support/bug-reports/", {"description": "El botón no guarda", **data}, format="json")
    assert response.status_code == status.HTTP_201_CREATED, response.data
    return response.data


@pytest.mark.contract
class TestBugReports:
    @pytest.mark.django_db
    def test_report_fires_the_fixer_after_commit(
        self, session_client, tasks, django_capture_on_commit_callbacks, instance
    ):
        with django_capture_on_commit_callbacks(execute=True):
            bug = report_bug(session_client, urgent=True, url="/ws/projects/")
        assert bug["status"] == "open"
        assert bug["severity"] == "bloqueante"
        tasks["fire_bug"].assert_called_once_with("nuevo reporte de un usuario", bug["id"], "high")

    @pytest.mark.django_db
    def test_mine_lists_only_my_manual_reports(self, session_client):
        report_bug(session_client)
        BugReport.objects.create(description="otro", source=BugReport.Source.AUTO)
        response = session_client.get("/api/support/bug-reports/mine/")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 1

    @pytest.mark.django_db
    def test_admin_list_is_admin_only(self, session_client, admin_client):
        assert session_client.get("/api/support/bug-reports/").status_code == status.HTTP_403_FORBIDDEN
        assert admin_client.get("/api/support/bug-reports/").status_code == status.HTTP_200_OK

    @pytest.mark.django_db
    def test_auto_reports_group_by_fingerprint(self, session_client):
        payload = {"fingerprint": "fe_abc123", "error_type": "TypeError", "message": "x is undefined"}
        first = session_client.post("/api/support/bug-reports/auto/", payload, format="json")
        second = session_client.post("/api/support/bug-reports/auto/", payload, format="json")
        assert first.status_code == second.status_code == status.HTTP_202_ACCEPTED
        assert first.data["id"] == second.data["id"]
        assert second.data["occurrences"] == 2


@pytest.mark.contract
class TestBugAgentApi:
    @pytest.mark.django_db
    def test_requires_the_bug_key(self, session_client):
        report_bug(session_client)
        assert APIClient().get("/api/agent/bugs/").status_code in (401, 403)
        wrong = APIClient()
        wrong.credentials(HTTP_AUTHORIZATION="Bearer nope")
        assert wrong.get("/api/agent/bugs/").status_code == status.HTTP_401_UNAUTHORIZED
        feature_key = APIClient()
        feature_key.credentials(HTTP_AUTHORIZATION=f"Bearer {FEATURE_KEY}")
        assert feature_key.get("/api/agent/bugs/").status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.django_db
    def test_claim_progress_message_resolve(self, session_client, bug_agent, tasks):
        bug = report_bug(session_client)
        base = f"/api/agent/bugs/{bug['id']}"

        queue = bug_agent.get("/api/agent/bugs/")
        assert [b["id"] for b in queue.data] == [bug["id"]]

        assert bug_agent.put(f"{base}/progress/", {"phase": "investigando"}, format="json").status_code == 409
        assert bug_agent.put(f"{base}/claim/").data["status"] == "in_progress"
        assert bug_agent.put(f"{base}/progress/", {"phase": "investigando"}, format="json").status_code == 200

        bad = bug_agent.put(f"{base}/set-message/", {"category": "Inventada"}, format="json")
        assert bad.status_code == status.HTTP_400_BAD_REQUEST
        card = {"resolved_message": "Ya se guarda.", "display_title": "No se guardaba", "category": "Work items"}
        assert bug_agent.put(f"{base}/set-message/", card, format="json").status_code == 200

        resolved = bug_agent.put(f"{base}/resolve/", {"commit_hash": "abc1234"}, format="json")
        assert resolved.data["status"] == "resolved"
        bug_agent.put(f"{base}/resolve/", {}, format="json")
        # the reporter is emailed once, however many times CI retries the resolve (no instance admins here)
        assert tasks["email"].call_count == 1

    @pytest.mark.django_db
    def test_blocked_bug_leaves_the_queue(self, session_client, bug_agent, admin_client):
        bug = report_bug(session_client)
        bug_agent.put(f"/api/agent/bugs/{bug['id']}/claim/")
        bug_agent.put(f"/api/agent/bugs/{bug['id']}/blocked/", {"reason": "toca auth"}, format="json")
        assert bug_agent.get("/api/agent/bugs/").data == []
        assert bug_agent.put(f"/api/agent/bugs/{bug['id']}/claim/").status_code == 409

        admin_client.post("/api/support/bug-reports/bulk/", {"action": "unblock", "ids": [bug["id"]]}, format="json")
        assert len(bug_agent.get("/api/agent/bugs/").data) == 1

    @pytest.mark.django_db
    def test_mark_fixed_is_idempotent(self, session_client, bug_agent):
        bug = report_bug(session_client)
        url = f"/api/agent/bugs/{bug['id']}/mark-fixed/"
        assert bug_agent.put(url, {"commit_hash": "abc"}, format="json").data["status"] == "fixed"
        assert bug_agent.put(url, {}, format="json").data["status"] == "fixed"

    @pytest.mark.django_db
    def test_to_feature_files_the_suggestion_in_the_reporters_name(self, session_client, bug_agent, create_user):
        bug = report_bug(session_client)
        payload = {"title": "Exportar a CSV", "problem": "Necesito sacar la lista", "message": "Lo pasamos."}
        response = bug_agent.put(f"/api/agent/bugs/{bug['id']}/to-feature/", payload, format="json")
        assert response.status_code == status.HTTP_200_OK
        feature = FeatureRequest.objects.get(id=response.data["feature_id"])
        assert feature.requested_by == create_user
        assert BugReport.objects.get(id=bug["id"]).derived_feature == feature

    @pytest.mark.django_db
    def test_pipeline_incident_is_a_blocking_bug(self, bug_agent, tasks):
        payload = {"kind": "batch-conflict", "branch": "claude/x"}
        first = bug_agent.post("/api/agent/bugs/pipeline-incident/", payload, format="json")
        second = bug_agent.post("/api/agent/bugs/pipeline-incident/", payload, format="json")
        assert first.data["id"] == second.data["id"]
        assert first.data["severity"] == "bloqueante"
        assert tasks["fire_bug"].call_args.args[2] == "urgent"


@pytest.mark.contract
class TestFeaturePipeline:
    def spec(self, **overrides):
        return {
            "summary": "Resumen",
            "approach": "Enfoque",
            "effort": "M",
            "blast_radius": "medium",
            "flag_key": "exportCsv",
            **overrides,
        }

    @pytest.mark.django_db
    def test_disabled_agent_leaves_the_request_submitted(self, session_client, django_capture_on_commit_callbacks):
        with django_capture_on_commit_callbacks(execute=True):
            response = session_client.post(
                "/api/support/feature-requests/",
                {"title": "Exportar a CSV", "problem": "Necesito sacar la lista de tareas a una planilla"},
                format="json",
            )
        assert response.data["status"] == "submitted"

    @pytest.mark.django_db
    def test_spec_approval_build_merge_and_flag(
        self,
        session_client,
        admin_client,
        feature_agent,
        feature_agent_enabled,
        tasks,
        django_capture_on_commit_callbacks,
    ):
        with django_capture_on_commit_callbacks(execute=True):
            created = session_client.post(
                "/api/support/feature-requests/",
                {"title": "Exportar a CSV", "problem": "Necesito sacar la lista de tareas a una planilla"},
                format="json",
            ).data
        feature_id = created["id"]
        assert FeatureRequest.objects.get(id=feature_id).status == "spec_running"
        assert tasks["fire_feature"].call_args.args[:2] == (feature_id, "SPEC")

        base = f"/api/agent/features/{feature_id}"
        spec = feature_agent.put(f"{base}/spec/", self.spec(), format="json")
        assert spec.data["status"] == "spec_ready"
        # the agent has no route to approve its own work
        assert feature_agent.put(f"{base}/approve/", {}, format="json").status_code == 404

        with django_capture_on_commit_callbacks(execute=True):
            approved = admin_client.post(f"/api/support/feature-requests/{feature_id}/approve/", {}, format="json")
        assert approved.status_code == status.HTTP_200_OK
        assert FeatureRequest.objects.get(id=feature_id).status == "building"
        assert tasks["fire_feature"].call_args.args[:2] == (feature_id, "BUILD")

        assert feature_agent.put(f"{base}/needs-info/", {"questions": ["?"]}, format="json").status_code == 409
        assert feature_agent.put(f"{base}/progress/", {"phase": "implementando"}, format="json").status_code == 200
        assert feature_agent.put(f"{base}/build-status/", {"state": "queued"}, format="json").data["status"] == "queued"
        assert feature_agent.put(f"{base}/merged/", {"commit_hash": "abc"}, format="json").data["status"] == "merged"

        flag = AgentFeatureFlag.objects.get(key="exportCsv")
        assert flag.enabled is False
        assert session_client.get("/api/support/feature-flags/").data["enabled"] == []
        admin_client.post(f"/api/support/feature-requests/{feature_id}/flag/", {"enabled": True}, format="json")
        assert session_client.get("/api/support/feature-flags/").data["enabled"] == ["exportCsv"]

    @pytest.mark.django_db
    def test_low_impact_first_spec_approves_itself(
        self, session_client, feature_agent, feature_agent_enabled, django_capture_on_commit_callbacks
    ):
        with django_capture_on_commit_callbacks(execute=True):
            created = session_client.post(
                "/api/support/feature-requests/",
                {"title": "Ver fecha de alta", "problem": "Quiero ver cuándo se creó cada proyecto en la lista"},
                format="json",
            ).data
        with django_capture_on_commit_callbacks(execute=True):
            response = feature_agent.put(
                f"/api/agent/features/{created['id']}/spec/", self.spec(blast_radius="low"), format="json"
            )
        assert response.data["status"] == "approved"
        assert FeatureRequest.objects.get(id=created["id"]).status == "building"

    @pytest.mark.django_db
    def test_non_admin_cannot_decide(self, session_client):
        feature = FeatureRequest.objects.create(title="Algo nuevo", problem="p" * 30, status="spec_ready")
        response = session_client.post(f"/api/support/feature-requests/{feature.id}/approve/", {}, format="json")
        assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.unit
class TestUrgency:
    @pytest.mark.django_db
    def test_classification(self):
        assert classify_urgency(BugReport(description="ResizeObserver loop limit exceeded")) == "noise"
        assert classify_urgency(BugReport(description="x", occurrences=10)) == "urgent"
        assert classify_urgency(BugReport(description="x", affected_user_ids=["a", "b"])) == "high"
        assert classify_urgency(BugReport(description="x", severity="bloqueante")) == "high"
        assert classify_urgency(BugReport(description="x", severity="sugerencia")) == "low"
        assert classify_urgency(BugReport(description="x")) == "medium"
