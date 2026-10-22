# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from unittest import mock

import uuid

import pytest
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from plane.db.models import AgentFeatureFlag, AgentPipelineConfig, BugReport, FeatureRequest, User
from plane.license.models import Instance, InstanceAdmin
from plane.agent_api.serialize import feature_summary
from plane.utils.agent_pipeline.features import lane_busy, request_build, request_spec

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


@pytest.mark.contract
class TestTheBuildLane:
    @pytest.mark.django_db
    def test_a_blocked_build_does_not_hold_the_lane(self, create_user, agent_on, tasks):
        own_feature(create_user, status=S.BUILDING, build={"blocked_at": "2026-10-16T00:00:00+00:00"})
        assert lane_busy() is False
        waiting = own_feature(create_user, status=S.APPROVED, flag_key="next")
        assert request_build(waiting) == (True, "queued")
        assert lane_busy() is True

    @pytest.mark.django_db
    def test_a_blocked_build_tells_admins_and_frees_the_lane(
        self, create_user, agent_on, tasks, monkeypatch, django_capture_on_commit_callbacks
    ):
        key = "f" * 64
        monkeypatch.setenv("OPS_FEATURE_AGENT_API_KEY", key)
        agent = User.objects.create(email="agent@zil.global", username=uuid.uuid4().hex, is_active=True)
        monkeypatch.setenv("AGENT_ADMIN_EMAIL", agent.email)
        building = own_feature(create_user, status=S.BUILDING, build={"claimed_at": "2026-10-16T00:00:00+00:00"})
        waiting = own_feature(create_user, status=S.APPROVED, flag_key="next")
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {key}")
        with (
            mock.patch("plane.utils.agent_pipeline.notify.admins_feature_build_blocked") as admins,
            django_capture_on_commit_callbacks(execute=True),
        ):
            response = client.post(
                f"/api/agent/features/{building.id}/build-status/",
                {"state": "blocked", "note": "Toca un archivo de la lista protegida"},
                format="json",
            )
        assert response.status_code == status.HTTP_200_OK, response.data
        admins.assert_called_once()
        waiting.refresh_from_db()
        assert waiting.status == S.BUILDING

    @pytest.mark.django_db
    def test_a_new_run_starts_without_the_previous_runs_note_and_progress(self, create_user, agent_on, tasks):
        old = {
            "runs": 1,
            "last_note": "Sin señales de vida",
            "progress": [{"phase": "terminando", "note": "", "at": "x"}],
        }
        feature = own_feature(create_user, status=S.APPROVED, flag_key="again", build=old)
        assert request_build(feature) == (True, "queued")
        feature.refresh_from_db()
        assert feature.build["last_note"] == "" and feature.build["progress"] == [] and feature.build["runs"] == 2

    @pytest.mark.django_db
    def test_a_stale_copy_cannot_start_a_build(self, create_user, agent_on, tasks):
        feature = own_feature(create_user, status=S.APPROVED, flag_key="x1")
        FeatureRequest.objects.filter(id=feature.id).update(status=S.REJECTED)
        assert request_build(feature) == (False, "status rejected")
        tasks["fire_feature"].assert_not_called()

    @pytest.mark.django_db
    @pytest.mark.parametrize("state", [S.IN_REVIEW, S.QUEUED])
    def test_in_review_and_queued_can_be_rejected(self, admin_client, create_user, tasks, state):
        feature = own_feature(create_user, status=state)
        response = admin_client.post(
            f"/api/support/feature-requests/{feature.id}/reject/", {"notes": "No va"}, format="json"
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.data["status"] == "rejected"

    @pytest.mark.django_db
    def test_answered_question_is_flagged_for_the_board(self, create_user):
        feature = own_feature(
            create_user,
            status=S.NEEDS_INFO,
            comments=[
                {"role": "agent", "text": "- ¿Qué formato?", "at": "1", "author_name": ""},
                {"role": "user", "text": "CSV", "at": "2", "author_name": "Ana"},
            ],
        )
        assert feature_summary(feature)["answered"] is True
        feature.comments = feature.comments[:1]
        assert feature_summary(feature)["answered"] is False


@pytest.mark.contract
class TestReporterViews:
    @pytest.mark.django_db
    def test_send_to_fixer_waits_for_a_fix_pending_its_publication(self, admin_client, create_user):
        bug = BugReport.objects.create(reported_by=create_user, description="No guarda", status=BugReport.Status.FIXED)
        with mock.patch("plane.utils.agent_pipeline.routines.fire_bug_routine", return_value={"fired": True}) as fired:
            response = admin_client.post(f"/api/support/bug-reports/{bug.id}/send-to-fixer/", format="json")
        # A new session would start without the pending fix, write it again and conflict with it.
        assert response.status_code == status.HTTP_409_CONFLICT and "próxima publicación" in response.data["error"]
        fired.assert_not_called()
        bug.refresh_from_db()
        assert bug.status == BugReport.Status.FIXED

    @pytest.mark.django_db
    def test_the_reporter_does_not_get_triage_fields(self, session_client, create_user):
        bug = BugReport.objects.create(
            reported_by=create_user, description="No guarda", admin_notes="interno", blocked_reason="denylist"
        )
        detail = session_client.get(f"/api/support/bug-reports/{bug.id}/").data
        mine = session_client.get("/api/support/bug-reports/mine/").data[0]
        for data in (detail, mine):
            assert "admin_notes" not in data and "blocked_reason" not in data and "commit_hash" not in data


@pytest.mark.contract
class TestRoundFour:
    @pytest.mark.django_db
    def test_reopen_clears_an_old_block_and_hides_its_reason(self, session_client, create_user, tasks):
        bug = BugReport.objects.create(
            reported_by=create_user,
            description="No guarda",
            status=BugReport.Status.RESOLVED,
            blocked_at=timezone.now(),
            blocked_reason="denylist",
        )
        with mock.patch("plane.app.views.support.bug_report._fire"):
            response = session_client.post(
                f"/api/support/bug-reports/{bug.id}/reopen/", {"comment": "Sigue pasando"}, format="json"
            )
        assert response.status_code == status.HTTP_200_OK, response.data
        assert "blocked_reason" not in response.data
        bug.refresh_from_db()
        assert bug.status == BugReport.Status.OPEN and bug.blocked_at is None

    @pytest.mark.django_db
    def test_blocked_filter_lists_only_reports_still_waiting(self, admin_client, create_user):
        waiting = BugReport.objects.create(reported_by=create_user, description="a", blocked_at=timezone.now())
        BugReport.objects.create(
            reported_by=create_user, description="b", blocked_at=timezone.now(), status=BugReport.Status.RESOLVED
        )
        rows = admin_client.get("/api/support/bug-reports/", {"blocked": "true"}).data
        assert [row["id"] for row in rows] == [str(waiting.id)]

    @pytest.mark.django_db
    def test_send_to_fixer_clears_the_previous_close(self, admin_client, create_user):
        bug = BugReport.objects.create(
            reported_by=create_user,
            description="x",
            status=BugReport.Status.RESOLVED,
            resolved_at=timezone.now(),
            fixed_at=timezone.now(),
        )
        with mock.patch("plane.utils.agent_pipeline.routines.fire_bug_routine", return_value={"fired": True}):
            admin_client.post(f"/api/support/bug-reports/{bug.id}/send-to-fixer/", format="json")
        bug.refresh_from_db()
        assert bug.resolved_at is None and bug.fixed_at is None

    @pytest.mark.django_db
    def test_run_limit_hold_tells_admins(self, create_user, agent_on, tasks):
        feature = own_feature(create_user, status=S.APPROVED, flag_key="tired", build={"runs": 3})
        with mock.patch("plane.utils.agent_pipeline.notify.admins_feature_build_blocked") as admins:
            assert request_build(feature) == (False, "build run limit")
        admins.assert_called_once()
        feature.refresh_from_db()
        assert feature.status == S.ON_HOLD

    @pytest.mark.django_db
    def test_a_failed_reanalysis_keeps_a_ready_spec_ready(self, create_user, agent_on):
        from plane.bgtasks.agent_pipeline_task import fire_feature_routine_task

        feature = own_feature(
            create_user, status=S.SPEC_RUNNING, spec={"generated_at": "2026-10-01T00:00:00+00:00"}, spec_runs=2
        )
        failed = {"fired": False, "reason": "post failed"}
        with mock.patch("plane.utils.agent_pipeline.routines.fire_feature_routine", return_value=failed):
            fire_feature_routine_task(str(feature.id), "SPEC", "rehacer")
        feature.refresh_from_db()
        # The failed attempt counts toward the cap: retries are bounded.
        assert feature.status == S.SPEC_READY and feature.spec_runs == 2

    @pytest.mark.django_db
    def test_the_sweep_restarts_a_pending_analysis(self, create_user, agent_on, tasks):
        from plane.bgtasks.agent_pipeline_task import feature_run_sweep

        pending = own_feature(create_user, status=S.SUBMITTED)
        feature_run_sweep()
        pending.refresh_from_db()
        assert pending.status == S.SPEC_RUNNING
        tasks["fire_feature"].assert_called_once()

    @pytest.mark.django_db
    def test_the_build_queue_goes_by_approval_date(self, create_user, agent_on, tasks):
        from plane.utils.agent_pipeline.features import drain_feature_queue

        later = own_feature(
            create_user, status=S.APPROVED, flag_key="later", approval={"at": "2026-10-05T00:00:00+00:00"}
        )
        first = own_feature(
            create_user, status=S.APPROVED, flag_key="first", approval={"at": "2026-10-01T00:00:00+00:00"}
        )
        later.save()  # a comment or any save bumps updated_at
        assert drain_feature_queue() == (True, "queued")
        first.refresh_from_db()
        assert first.status == S.BUILDING


@pytest.mark.contract
class TestRoundFive:
    @pytest.mark.django_db
    def test_a_demoted_director_no_longer_auto_approves(self, create_user, workspace):
        from plane.db.models import WorkspaceMember
        from plane.utils.agent_pipeline.permissions import is_workspace_director

        assert is_workspace_director(create_user, workspace) is True
        WorkspaceMember.objects.filter(workspace=workspace, member=create_user).update(role=15)
        assert is_workspace_director(create_user, workspace) is False

    @pytest.mark.django_db
    def test_admin_links_go_through_a_workspace_the_admin_is_in(self, create_user, workspace, tasks, settings):
        from plane.db.models import Workspace, WorkspaceMember
        from plane.utils.agent_pipeline import notify

        settings.WEB_URL = "http://ops.test"
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
        mine = Workspace.objects.create(name="Admin", owner=admin, slug="admin-ws")
        WorkspaceMember.objects.create(workspace=mine, member=admin, role=20)
        feature = own_feature(create_user, workspace=workspace)

        notify.admins_new_feature(feature)

        args = tasks["email"].call_args[0]
        assert args[0] == ["owner@zil.global"]
        assert args[5] == f"http://ops.test/admin-ws/support?feature={feature.id}"

    @pytest.mark.django_db
    def test_auto_approval_mail_says_what_happened(self, create_user, agent_on, tasks):
        from plane.agent_api.features import _start_auto_approved

        own_feature(create_user, status=S.BUILDING)  # the lane is taken
        waiting = own_feature(create_user, status=S.APPROVED, flag_key="later")
        with mock.patch("plane.utils.agent_pipeline.notify.requester_feature_update") as told:
            _start_auto_approved(waiting)
        assert told.call_args[0][1] == "Tu sugerencia quedó aprobada"

    @pytest.mark.django_db
    def test_a_throttled_suggestion_says_why(self, session_client):
        from plane.app.views.support.feature_request import FeatureRequestCreateThrottle

        with (
            mock.patch.object(FeatureRequestCreateThrottle, "allow_request", return_value=False),
            mock.patch.object(FeatureRequestCreateThrottle, "wait", return_value=600),
        ):
            response = session_client.post(
                "/api/support/feature-requests/",
                {"title": "Exportar", "problem": "No puedo exportar los work items del ciclo"},
                format="json",
            )
        assert response.status_code == 429
        assert "varias sugerencias" in response.data["detail"]

    @pytest.mark.django_db
    def test_a_stale_agent_message_is_cleared_when_a_person_closes_or_reopens(self, admin_client, create_user, tasks):
        bug = BugReport.objects.create(
            reported_by=create_user, description="x", status=BugReport.Status.IN_PROGRESS, resolved_message="Ya quedó."
        )
        admin_client.post("/api/support/bug-reports/bulk/", {"action": "dismiss", "ids": [str(bug.id)]}, format="json")
        bug.refresh_from_db()
        assert bug.status == BugReport.Status.DISMISSED and bug.resolved_message == ""

    @pytest.mark.django_db
    def test_a_derived_report_carries_its_suggestions_status(self, session_client, create_user):
        merged = own_feature(create_user, status=S.MERGED)
        BugReport.objects.create(
            reported_by=create_user, description="x", status=BugReport.Status.DISMISSED, derived_feature=merged
        )
        mine = session_client.get("/api/support/bug-reports/mine/").data[0]
        assert mine["derived_feature_status"] == "merged"


@pytest.mark.contract
class TestRoundSix:
    @pytest.mark.django_db
    @pytest.mark.parametrize("previous", [S.NEEDS_INFO, S.ON_HOLD])
    def test_a_failed_analysis_goes_back_where_it_was_asked_from(self, create_user, agent_on, previous):
        from plane.bgtasks.agent_pipeline_task import fire_feature_routine_task

        feature = own_feature(
            create_user,
            status=S.SPEC_RUNNING,
            spec={"generated_at": "2026-10-01T00:00:00+00:00"},
            comments=[
                {"role": "agent", "text": "¿Qué formato?", "at": "2026-10-01T00:00:00+00:00"},
                {"role": "user", "text": "CSV", "at": "2026-10-01T01:00:00+00:00"},
            ],
        )
        failed = {"fired": False, "reason": "post failed"}
        with mock.patch("plane.utils.agent_pipeline.routines.fire_feature_routine", return_value=failed):
            fire_feature_routine_task(str(feature.id), "SPEC", "respuesta", previous)
        feature.refresh_from_db()
        # Not "ready to decide" with the answer never analysed, and a hold isn't lifted by a failure.
        assert feature.status == previous
        if previous == S.NEEDS_INFO:
            # Still answered: it waits for the admin who relaunches it, not for the requester again.
            assert feature_summary(feature)["answered"] is True

    @pytest.mark.django_db
    def test_the_request_records_where_the_analysis_was_asked_from(self, create_user, agent_on, tasks):
        feature = own_feature(create_user, status=S.NEEDS_INFO)
        assert request_spec(feature, "respuesta") == (True, "queued")
        assert tasks["fire_feature"].call_args.args[3] == S.NEEDS_INFO

    @pytest.mark.django_db
    def test_a_reanalysis_that_dies_keeps_the_spec_it_had(self, create_user, agent_on):
        from plane.bgtasks.agent_pipeline_task import feature_run_sweep
        from plane.utils.agent_pipeline.constants import FEATURE_RUN_EXPIRY, MAX_SPEC_RUNS

        feature = own_feature(
            create_user,
            status=S.SPEC_RUNNING,
            spec={"generated_at": "2026-10-01T00:00:00+00:00"},
            spec_runs=MAX_SPEC_RUNS,
            spec_requested_at=timezone.now() - FEATURE_RUN_EXPIRY * 2,
        )
        feature_run_sweep()
        feature.refresh_from_db()
        # Past the run cap the sweep never retries a "received" one: it sat there with its spec hidden.
        assert feature.status == S.SPEC_READY

    @pytest.mark.django_db
    def test_approving_a_redone_spec_after_the_run_cap_builds_it(
        self, admin_client, agent_on, tasks, django_capture_on_commit_callbacks
    ):
        from plane.utils.agent_pipeline.constants import MAX_BUILD_RUNS

        feature = FeatureRequest.objects.create(
            title="Algo nuevo",
            problem="p" * 30,
            status=S.SPEC_READY,
            flag_key="algoNuevo",
            build={"runs": MAX_BUILD_RUNS},
        )
        with django_capture_on_commit_callbacks(execute=True):
            response = admin_client.post(f"/api/support/feature-requests/{feature.id}/approve/", {}, format="json")
        assert response.status_code == status.HTTP_200_OK, response.data
        assert response.data["build"]["fired"] is True
        feature.refresh_from_db()
        assert feature.status == S.BUILDING

    @pytest.mark.django_db
    @pytest.mark.parametrize("action", ["archive", "dismiss"])
    def test_tidying_up_a_closed_report_keeps_its_answer(self, admin_client, create_user, action):
        bug = BugReport.objects.create(
            reported_by=create_user, description="x", status=BugReport.Status.RESOLVED, resolved_message="Se arregló."
        )
        admin_client.post("/api/support/bug-reports/bulk/", {"action": action, "ids": [str(bug.id)]}, format="json")
        bug.refresh_from_db()
        assert bug.resolved_message == "Se arregló."

    @pytest.mark.django_db
    def test_an_automatic_report_turned_into_a_suggestion_is_nobodys_and_waits_for_a_person(
        self, admin_client, create_user
    ):
        from plane.agent_api.features import should_auto_approve
        from plane.utils.agent_pipeline.bugs import derive_feature

        agent = User.objects.get(email="owner@zil.global")  # an instance admin, like the agent's own user
        crash = BugReport.objects.create(reported_by=create_user, description="x", source=BugReport.Source.AUTO)
        feature = derive_feature(
            crash, title="Exportar", problem="p" * 30, desired_outcome="", message="", agent_user=agent
        )
        assert feature.requested_by == agent

        feature.spec, feature.spec_runs = {"blast_radius": "medium", "generated_at": "2026-10-01"}, 1
        # The admin's shortcut is for an admin asking, not for the pipeline filing it.
        assert should_auto_approve(feature) is False

        # An admin's own report still gets it.
        own = BugReport.objects.create(reported_by=agent, description="y", source=BugReport.Source.MANUAL)
        theirs = derive_feature(own, title="Otra", problem="p" * 30, desired_outcome="", message="", agent_user=agent)
        theirs.spec, theirs.spec_runs = {"blast_radius": "medium", "generated_at": "2026-10-01"}, 1
        assert should_auto_approve(theirs) is True

    @pytest.mark.django_db
    def test_an_automatic_report_handed_to_workspace_names_no_reporter(self, monkeypatch, create_user):
        key = "b" * 64
        agent = User.objects.create(email="agent@zil.global", username=uuid.uuid4().hex, is_active=True)
        for name, value in {**ZIL_ENV, "OPS_BUG_AGENT_API_KEY": key, "AGENT_ADMIN_EMAIL": agent.email}.items():
            monkeypatch.setenv(name, value)
        crash = BugReport.objects.create(
            reported_by=create_user, description="Se cae al abrir", source=BugReport.Source.AUTO
        )
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {key}")
        with zil_answers(body={"id": "a" * 24, "trackingUrl": "http://ws.test/x"}) as post:
            response = client.put(
                f"/api/agent/bugs/{crash.id}/to-workspace/",
                {"diagnosis": "server/controllers/x.js:1 rompe", "message": "Sigue en Workspace."},
                format="json",
            )
        assert response.status_code == status.HTTP_200_OK, response.data
        sent = post.call_args.kwargs["json"]
        # The first person it happened to isn't its reporter there either.
        assert (sent["reporterEmail"], sent["source"]) == ("", "auto")

    @pytest.mark.django_db
    @pytest.mark.parametrize(("decision", "heading"), [("approve", "quedó aprobada"), ("hold", "Pausamos")])
    def test_the_requester_hears_an_admins_approval_or_hold(self, admin_client, create_user, decision, heading):
        feature = own_feature(create_user, status=S.SPEC_READY, flag_key="exportar")
        with mock.patch("plane.utils.agent_pipeline.notify.requester_feature_update") as told:
            response = admin_client.post(f"/api/support/feature-requests/{feature.id}/{decision}/", {}, format="json")
        assert response.status_code == status.HTTP_200_OK, response.data
        assert heading in told.call_args[0][1]

    @pytest.mark.django_db
    def test_a_build_that_fails_on_every_push_is_announced_once(self, monkeypatch, create_user, tasks):
        key = "f" * 64
        agent = User.objects.create(email="agent@zil.global", username=uuid.uuid4().hex, is_active=True)
        monkeypatch.setenv("OPS_FEATURE_AGENT_API_KEY", key)
        monkeypatch.setenv("AGENT_ADMIN_EMAIL", agent.email)
        feature = own_feature(create_user, status=S.BUILDING, flag_key="exportar", build={"claimed_at": "2026-10-16"})
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {key}")
        url = f"/api/agent/features/{feature.id}/build-status/"
        with mock.patch("plane.utils.agent_pipeline.notify.admins_feature_build_blocked") as admins:
            for note in ("No pasó.", "Tampoco ahora."):
                response = client.put(url, {"state": "blocked", "note": note}, format="json")
                assert response.status_code == status.HTTP_200_OK, response.data
        admins.assert_called_once()
        feature.refresh_from_db()
        assert feature.build["last_note"] == "Tampoco ahora."

    @pytest.mark.django_db
    def test_the_requester_hears_a_paused_suggestion_resume(self, admin_client, create_user):
        feature = own_feature(create_user, status=S.ON_HOLD, flag_key="exportar")
        with mock.patch("plane.utils.agent_pipeline.notify.requester_feature_update") as told:
            response = admin_client.post(f"/api/support/feature-requests/{feature.id}/rebuild/", {}, format="json")
        assert response.status_code == status.HTTP_200_OK, response.data
        assert "Tu sugerencia" in told.call_args[0][1]

    @pytest.mark.django_db
    def test_a_plain_rebuild_is_not_news_to_the_requester(self, admin_client, create_user):
        feature = own_feature(create_user, status=S.BUILDING, flag_key="exportar", build={"blocked_at": "2026-10-16"})
        with mock.patch("plane.utils.agent_pipeline.notify.requester_feature_update") as told:
            response = admin_client.post(f"/api/support/feature-requests/{feature.id}/rebuild/", {}, format="json")
        assert response.status_code == status.HTTP_200_OK, response.data
        told.assert_not_called()


@pytest.mark.contract
class TestRoundSeven:
    @pytest.mark.django_db
    def test_the_relayed_text_keeps_one_line_per_question(self):
        from django.core import mail

        from plane.bgtasks.agent_pipeline_task import send_support_email_task

        config = ("smtp", "", "", "25", "0", "0", "soporte@zil.global")
        with mock.patch("plane.bgtasks.agent_pipeline_task.get_email_configuration", return_value=config):
            send_support_email_task(
                ["ana@zil.global"],
                "Necesitamos un dato",
                "Necesitamos un dato",
                ["Hola Ana,", "Para avanzar necesitamos que nos cuentes:\n- ¿Qué formato?\n- ¿Para quién?"],
                "Ver mi seguimiento",
                "http://ops.test/x",
            )
        # The Zil relay renders this text line by line, with the subject as its title.
        assert mail.outbox[0].body.split("\n") == [
            "Hola Ana,",
            "Para avanzar necesitamos que nos cuentes:",
            "- ¿Qué formato?",
            "- ¿Para quién?",
        ]

    @pytest.mark.django_db
    def test_an_admin_filing_a_suggestion_is_not_told_about_it(self, admin_client, tasks):
        response = admin_client.post(
            "/api/support/feature-requests/",
            {
                "title": "Exportar a CSV",
                "problem": "No puedo exportar los work items a una planilla",
                "priority": "media",
            },
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.data
        assert "owner@zil.global" not in [call.args[0][0] for call in tasks["email"].call_args_list]

    @pytest.mark.django_db
    def test_an_admin_requester_gets_the_admin_email_only_when_the_spec_is_ready(self, admin_client, agent_on):
        from plane.agent_api.features import AgentFeatureActionEndpoint

        admin = User.objects.get(email="owner@zil.global")
        feature = own_feature(admin, status=S.SPEC_RUNNING, spec_runs=2)
        request = mock.Mock(
            data={"summary": "Exportar", "approach": "x", "blast_radius": "high", "effort": "M", "flag_key": "exportar"}
        )
        with (
            mock.patch("plane.utils.agent_pipeline.notify.admins_feature_needs_decision") as admins,
            mock.patch("plane.utils.agent_pipeline.notify.requester_feature_update") as told,
            mock.patch("plane.agent_api.features._valid", side_effect=lambda _s, r: r.data),
        ):
            AgentFeatureActionEndpoint().do_spec(request, feature)
        admins.assert_called_once()
        told.assert_not_called()

    @pytest.mark.django_db
    def test_rejecting_your_own_suggestion_sends_you_nothing(self, admin_client):
        admin = User.objects.get(email="owner@zil.global")
        feature = own_feature(admin, status=S.SPEC_READY)
        with mock.patch("plane.utils.agent_pipeline.notify.requester_feature_update") as told:
            admin_client.post(f"/api/support/feature-requests/{feature.id}/reject/", {"notes": "No."}, format="json")
        told.assert_not_called()

    @pytest.mark.django_db
    @pytest.mark.parametrize(("fixed", "says_deploying"), [(True, True), (False, False)])
    def test_the_resolved_email_mentions_a_deploy_only_for_a_code_fix(self, create_user, tasks, fixed, says_deploying):
        from plane.utils.agent_pipeline import notify

        bug = BugReport.objects.create(
            reported_by=create_user, description="x", fixed_at=timezone.now() if fixed else None
        )
        notify.bug_resolved(bug)
        paragraphs = tasks["email"].call_args[0][3]
        assert any("se está publicando" in p for p in paragraphs) is says_deploying

    @pytest.mark.django_db
    @pytest.mark.parametrize(
        ("fields", "shown"),
        [
            ({"resolved_message": "Se arregló.", "commit_hash": "abc"}, "resolved"),
            ({"resolved_message": "Se hace desde Ajustes."}, "dismissed"),
            ({}, "resolved"),
        ],
    )
    def test_an_archived_report_reads_as_it_ended_for_its_reporter(self, session_client, create_user, fields, shown):
        closed = BugReport.objects.create(
            reported_by=create_user,
            description="x",
            status=BugReport.Status.ARCHIVED,
            resolved_at=timezone.now(),
            **fields,
        )
        never = BugReport.objects.create(reported_by=create_user, description="y", status=BugReport.Status.ARCHIVED)
        # What the reporter's email link opens.
        assert session_client.get(f"/api/support/bug-reports/{closed.id}/").data["status"] == shown
        # Archived before anyone closed it: that one really didn't advance.
        assert session_client.get(f"/api/support/bug-reports/{never.id}/").data["status"] == "archived"

    @pytest.mark.django_db
    def test_the_button_survives_the_zil_relay(self):
        import re

        from django.template.loader import render_to_string

        html = render_to_string(
            "emails/support/notice.html",
            {"heading": "x", "paragraphs": ["y"], "cta_label": "Ver mi seguimiento", "cta_url": "http://ops.test/x"},
        )
        # Workspace's mailRelay takes the button from the html with this pattern (extractPrimaryCta).
        found = re.search(r"""<a\b[^>]*href=["'](https?://[^"']+)["'][^>]*>([\s\S]*?)</a>""", html)
        assert found and found.group(2).strip() == "Ver mi seguimiento"


@pytest.mark.contract
class TestRoundEight:
    @pytest.mark.django_db
    def test_reporting_has_a_ceiling_and_says_why(self, session_client):
        from plane.app.views.support.bug_report import BugReportCreateThrottle

        with (
            mock.patch.object(BugReportCreateThrottle, "allow_request", return_value=False),
            mock.patch.object(BugReportCreateThrottle, "wait", return_value=600),
            mock.patch("plane.utils.agent_pipeline.notify.admins_new_bug") as admins,
        ):
            response = session_client.post(
                "/api/support/bug-reports/", {"description": "No guarda", "urgent": True}, format="json"
            )
        assert response.status_code == 429
        assert "varios reportes" in response.data["detail"]
        admins.assert_not_called()

    @pytest.mark.django_db
    def test_the_admins_read_the_impact_in_spanish(self, create_user, tasks):
        from plane.utils.agent_pipeline import notify

        admin = User.objects.create(email="owner@zil.global", username=uuid.uuid4().hex, is_active=True)
        instance = Instance.objects.create(
            instance_name="Test Instance",
            instance_id=str(uuid.uuid4()),
            current_version="1.0.0",
            domain="http://localhost:8000",
            last_checked_at=timezone.now(),
            is_setup_done=True,
        )
        InstanceAdmin.objects.create(instance=instance, user=admin, role=20)
        feature = own_feature(create_user, spec={"summary": "Exportar", "blast_radius": "medium"})
        notify.admins_feature_needs_decision(feature)
        assert "Impacto estimado: medio" in tasks["email"].call_args[0][3]

    @pytest.mark.django_db
    def test_a_crash_handed_to_workspace_stays_one_report_while_its_fix_ships(self, create_user):
        from datetime import timedelta

        from plane.utils.agent_pipeline.bugs import file_auto_bug_report

        first, _ = file_auto_bug_report(key="TypeError:x", description="Se cae", user=create_user)
        BugReport.objects.filter(id=first.id).update(
            status=BugReport.Status.DISMISSED, workspace_bug_id="a" * 24, resolved_at=timezone.now()
        )
        again, escalate = file_auto_bug_report(key="TypeError:x", description="Se cae", user=create_user)
        # Not a new report for the fixer to hand over again (a duplicate in Workspace).
        assert again.id == first.id and escalate is False
        assert BugReport.objects.filter(fingerprint=first.fingerprint).count() == 1

        # Archived by an admin: still the same report while its fix ships.
        BugReport.objects.filter(id=first.id).update(status=BugReport.Status.ARCHIVED)
        archived, escalate = file_auto_bug_report(key="TypeError:x", description="Se cae", user=create_user)
        assert archived.id == first.id and escalate is False

        BugReport.objects.filter(id=first.id).update(resolved_at=timezone.now() - timedelta(days=8))
        later, escalate = file_auto_bug_report(key="TypeError:x", description="Se cae", user=create_user)
        # Still happening a week later: news again.
        assert later.id != first.id and escalate is True

    @pytest.mark.django_db
    def test_an_archived_report_a_person_resolved_reads_resolved(self, session_client, create_user, admin_client):
        admin = User.objects.get(email="owner@zil.global")
        bug = BugReport.objects.create(
            reported_by=create_user,
            description="x",
            status=BugReport.Status.ARCHIVED,
            resolved_at=timezone.now(),
            resolved_by=admin,
            resolved_message="Ya quedó.",
        )
        response = session_client.get(f"/api/support/bug-reports/{bug.id}/")
        assert response.data["status"] == "resolved"
        assert "resolved_by" not in response.data

    @pytest.mark.django_db
    def test_sending_it_back_forgets_the_previous_fix(self, session_client, create_user):
        bug = BugReport.objects.create(
            reported_by=create_user,
            description="x",
            status=BugReport.Status.RESOLVED,
            commit_hash="abc123",
            fixed_at=timezone.now(),
            resolved_at=timezone.now(),
            resolved_by=create_user,
        )
        with mock.patch("plane.app.views.support.bug_report._fire"):
            session_client.post(
                f"/api/support/bug-reports/{bug.id}/reopen/", {"comment": "Sigue pasando"}, format="json"
            )
        bug.refresh_from_db()
        assert bug.status == BugReport.Status.OPEN and bug.commit_hash == "" and bug.resolved_by is None


@pytest.mark.contract
class TestRoundTen:
    CONFIG = ("smtp", "", "", "25", "0", "0", "soporte@zil.global")

    def _send(self, error):
        import requests as http

        from plane.bgtasks.agent_pipeline_task import send_support_email_task

        class Retried(Exception):
            pass

        def flaky_send(message, *args, **kwargs):
            if message.to == ["ana@zil.global"]:
                raise error
            return 1

        with (
            mock.patch("plane.bgtasks.agent_pipeline_task.get_email_configuration", return_value=self.CONFIG),
            mock.patch("django.core.mail.EmailMultiAlternatives.send", autospec=True, side_effect=flaky_send),
            mock.patch.object(send_support_email_task, "retry", side_effect=Retried) as retry,
        ):
            try:
                send_support_email_task(["ana@zil.global", "beto@zil.global"], "Asunto", "Asunto", ["Hola,"])
            except Retried:
                pass
        return retry, http

    @pytest.mark.django_db
    def test_a_mail_the_relay_never_got_is_retried_for_who_missed_it(self):
        import requests as http

        retry, _ = self._send(http.ConnectionError("down"))
        # Only Ana goes again: Beto already has it.
        assert retry.call_args.kwargs["args"][0] == ["ana@zil.global"]

    @pytest.mark.django_db
    def test_a_timeout_is_not_retried_because_it_may_have_gone_out(self):
        import requests as http

        retry, _ = self._send(http.ReadTimeout("slow"))
        retry.assert_not_called()

    @pytest.mark.django_db
    def test_a_fix_waiting_for_its_deploy_is_not_sent_back(self, session_client, create_user):
        bug = BugReport.objects.create(
            reported_by=create_user, description="x", status=BugReport.Status.FIXED, fixed_at=timezone.now()
        )
        with mock.patch("plane.app.views.support.bug_report._fire") as fired:
            response = session_client.post(
                f"/api/support/bug-reports/{bug.id}/reopen/", {"comment": "Sigue pasando"}, format="json"
            )
        assert response.status_code == 409 and "próxima publicación" in response.data["error"]
        fired.assert_not_called()
        bug.refresh_from_db()
        assert bug.status == BugReport.Status.FIXED

    @pytest.mark.django_db
    def test_what_ci_tells_the_next_session_never_reaches_the_reporter(self, session_client, create_user):
        from plane.utils.agent_pipeline.bugs import progress_entry

        bug = BugReport.objects.create(
            reported_by=create_user,
            description="x",
            status=BugReport.Status.IN_PROGRESS,
            progress=[progress_entry("dudas", "El arreglo no pasó las pruebas.", "CI rejected: https://ci/run/1")],
        )
        step = session_client.get(f"/api/support/bug-reports/{bug.id}/").data["progress"][0]
        assert step["note"] == "El arreglo no pasó las pruebas." and "for_agent" not in step


@pytest.mark.contract
class TestRoundEleven:
    def _trigger(self, mode, previous_failure=""):
        from plane.utils.agent_pipeline import routines

        env = {"ANTHROPIC_OPS_FEATURE_ROUTINE_URL": "http://routine", "ANTHROPIC_OPS_FEATURE_ROUTINE_TOKEN": "t"}
        with (
            mock.patch.dict("os.environ", env),
            mock.patch("plane.utils.agent_pipeline.routines.resolve_agent_key", return_value="k"),
            mock.patch("plane.utils.agent_pipeline.routines.post_routine", return_value=True) as post,
        ):
            routines.fire_feature_routine("f1", mode, title="Exportar", previous_failure=previous_failure)
        return post.call_args[0][2]

    def test_a_rebuild_continues_on_the_branch_the_last_attempt_pushed(self):
        text = self._trigger("BUILD", "CI rejected: https://ci/run/9")
        assert "git checkout -B feat/agent/f1 FETCH_HEAD" in text
        assert "Never force-push" in text and "https://ci/run/9" in text
        assert "plain Spanish" in text
        assert "checkout -B" not in self._trigger("SPEC")

    @pytest.mark.django_db
    def test_what_ci_leaves_for_the_rebuild_survives_it_and_the_requester_never_sees_it(
        self, session_client, create_user, admin_client, agent_on
    ):
        feature = own_feature(
            create_user,
            status=S.BUILDING,
            flag_key="exportar",
            build={"claimed_at": "2026-10-16", "for_agent": "CI rejected: https://ci/run/9"},
        )
        assert "for_agent" not in session_client.get(f"/api/support/feature-requests/{feature.id}/").data["build"]
        assert admin_client.get(f"/api/support/feature-requests/{feature.id}/").data["build"]["for_agent"]

        feature.status = S.APPROVED
        feature.save()
        request_build(feature, "decisión: rebuild")
        feature.refresh_from_db()
        assert feature.build["for_agent"] == "CI rejected: https://ci/run/9"

    @pytest.mark.django_db
    def test_something_ops_already_does_waits_for_a_person(self, create_user):
        from plane.agent_api.features import should_auto_approve

        feature = own_feature(create_user, spec_runs=1)
        feature.spec = {"blast_radius": "low", "already_exists": True, "generated_at": "2026-10-17"}
        # Nothing to build: no build session, no "ya empezamos a construirla".
        assert should_auto_approve(feature) is False
        feature.spec = {"blast_radius": "low", "generated_at": "2026-10-17"}
        assert should_auto_approve(feature) is True
        assert "already_exists" in TestRoundEleven()._trigger("SPEC")

    @pytest.mark.django_db
    def test_a_green_ci_run_forgets_the_earlier_failure(self, monkeypatch, create_user):
        key = "f" * 64
        agent = User.objects.create(email="agent@zil.global", username=uuid.uuid4().hex, is_active=True)
        monkeypatch.setenv("OPS_FEATURE_AGENT_API_KEY", key)
        monkeypatch.setenv("AGENT_ADMIN_EMAIL", agent.email)
        feature = own_feature(
            create_user,
            status=S.BUILDING,
            flag_key="exportar",
            build={"claimed_at": "2026-10-16", "for_agent": "run A"},
        )
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {key}")
        response = client.put(f"/api/agent/features/{feature.id}/build-status/", {"state": "in_review"}, format="json")
        assert response.status_code == status.HTTP_200_OK, response.data
        feature.refresh_from_db()
        assert "for_agent" not in feature.build


@pytest.mark.contract
class TestRoundTwelve:
    @pytest.mark.django_db
    def test_a_crash_someone_is_fixing_doesnt_start_another_session(self, create_user):
        from plane.utils.agent_pipeline.bugs import file_auto_bug_report
        from plane.utils.agent_pipeline.constants import ESCALATE_EVERY

        bug, _ = file_auto_bug_report(key="TypeError:y", description="Se cae", user=create_user)
        BugReport.objects.filter(id=bug.id).update(
            status=BugReport.Status.IN_PROGRESS, occurrences=ESCALATE_EVERY - 1, last_escalated_at=None
        )
        _, escalate = file_auto_bug_report(key="TypeError:y", description="Se cae", user=create_user)
        assert escalate is False

        BugReport.objects.filter(id=bug.id).update(status=BugReport.Status.OPEN, occurrences=ESCALATE_EVERY - 1)
        _, escalate = file_auto_bug_report(key="TypeError:y", description="Se cae", user=create_user)
        assert escalate is True

    @pytest.mark.django_db
    def test_with_the_fixer_off_a_closed_report_stays_closed(self, admin_client, create_user):
        config = AgentPipelineConfig.get()
        config.bug_agent_enabled = False
        config.save()
        bug = BugReport.objects.create(
            reported_by=create_user, description="x", status=BugReport.Status.RESOLVED, resolved_message="Listo."
        )
        response = admin_client.post(f"/api/support/bug-reports/{bug.id}/send-to-fixer/", format="json")
        assert response.status_code == status.HTTP_409_CONFLICT
        bug.refresh_from_db()
        assert bug.status == BugReport.Status.RESOLVED and bug.resolved_message == "Listo."

    @pytest.mark.django_db
    def test_the_admins_hear_it_already_exists(self, create_user, tasks, admin_client):
        from plane.utils.agent_pipeline import notify

        feature = own_feature(create_user, spec={"summary": "Se hace desde Vistas.", "already_exists": True})
        notify.admins_feature_needs_decision(feature)
        heading, paragraphs = tasks["email"].call_args[0][2], tasks["email"].call_args[0][3]
        assert heading == "Según el análisis, esto ya existe"
        assert any("aprobala y se cierra" in p for p in paragraphs)

    @pytest.mark.django_db
    def test_approving_what_already_exists_closes_it_without_a_build(self, create_user, tasks, admin_client):
        feature = own_feature(
            create_user,
            status=S.SPEC_READY,
            flag_key="yaExiste",
            spec={"summary": "Se hace desde Configuración > Estados.", "already_exists": True},
        )
        with mock.patch("plane.utils.agent_pipeline.notify.requester_feature_update") as told:
            response = admin_client.post(f"/api/support/feature-requests/{feature.id}/approve/", {}, format="json")
        assert response.status_code == status.HTTP_200_OK, response.data
        feature.refresh_from_db()
        assert feature.status == S.MERGED and feature.build["already_existed"] is True
        assert feature.approval["by_name"] is not None
        tasks["fire_feature"].assert_not_called()
        assert told.call_args[0][2] == "Se hace desde Configuración > Estados."
        assert AgentFeatureFlag.objects.get(key="yaExiste").enabled is True

    @pytest.mark.django_db
    def test_a_build_with_nothing_to_build_closes_instead_of_blocking(self, monkeypatch, create_user, tasks):
        key = "f" * 64
        agent = User.objects.create(email="agent@zil.global", username=uuid.uuid4().hex, is_active=True)
        monkeypatch.setenv("OPS_FEATURE_AGENT_API_KEY", key)
        monkeypatch.setenv("AGENT_ADMIN_EMAIL", agent.email)
        feature = own_feature(
            create_user, status=S.BUILDING, flag_key="rolProyecto", build={"claimed_at": "2026-10-22"}
        )
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {key}")
        url = f"/api/agent/features/{feature.id}/build-status/"
        assert client.put(url, {"state": "already_done"}, format="json").status_code == status.HTTP_409_CONFLICT
        with mock.patch("plane.utils.agent_pipeline.notify.admins_feature_build_blocked") as admins:
            response = client.put(url, {"state": "already_done", "note": "Dale rol Administrador."}, format="json")
        assert response.status_code == status.HTTP_200_OK, response.data
        admins.assert_not_called()
        feature.refresh_from_db()
        assert feature.status == S.MERGED and not feature.build.get("blocked_at")
        assert feature.build["last_note"] == "Dale rol Administrador."
        assert client.put(url, {"state": "already_done", "note": "x"}, format="json").status_code == 409
