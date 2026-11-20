# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""There is no team: whatever used to wait on a person goes back to its routine on its own.

- A blocked bug has a retry date and the claim sweep puts it back in the queue (1, 2, 4... days).
- A question to the requester: answered, the analysis reruns with it; unanswered for 3 days, it reruns
  deciding on stated assumptions.
- A spec past its run cap still goes back, after a growing wait.
"""

from datetime import timedelta
from unittest import mock

import pytest
from django.utils import timezone

from plane.db.models import AgentPipelineConfig, BugReport, FeatureRequest
from plane.utils.agent_pipeline import bugs
from plane.utils.agent_pipeline.constants import MAX_SPEC_RUNS, retry_wait

S = FeatureRequest.Status


@pytest.fixture(autouse=True)
def fire():
    with (
        mock.patch("plane.bgtasks.agent_pipeline_task.fire_feature_routine_task.delay") as feature,
        mock.patch("plane.utils.agent_pipeline.routines.fire_bug_routine", return_value={"fired": False}) as bug,
    ):
        yield {"feature": feature, "bug": bug}


@pytest.fixture
def agent_on(db):
    config = AgentPipelineConfig.get()
    config.feature_agent_enabled = True
    config.save()
    return config


def feature(**fields):
    return FeatureRequest.objects.create(title="Exportar", problem="No puedo exportar los work items", **fields)


@pytest.mark.unit
def test_the_wait_grows_and_never_passes_14_days():
    assert [retry_wait(c).days for c in range(6)] == [1, 2, 4, 8, 14, 14]


@pytest.mark.contract
class TestBlockedBugs:
    @pytest.mark.django_db
    def test_blocking_sets_a_retry_date_that_grows(self):
        bug = BugReport.objects.create(description="Se cae")
        now = timezone.now()
        bugs.block(bug, "Los revisores rechazaron el cambio", now)
        assert bug.retry_at == now + timedelta(days=1) and bug.block_cycles == 1
        bugs.block(bug, "Otra vez", now)
        assert bug.retry_at == now + timedelta(days=2) and bug.block_cycles == 2

    @pytest.mark.django_db
    def test_the_sweep_puts_it_back_in_the_queue_on_its_date(self):
        from plane.bgtasks.agent_pipeline_task import agent_claim_sweep

        now = timezone.now()
        due = BugReport.objects.create(description="Ya toca", blocked_at=now, retry_at=now - timedelta(minutes=1))
        later = BugReport.objects.create(description="Todavía no", blocked_at=now, retry_at=now + timedelta(days=1))
        result = agent_claim_sweep()
        assert result["requeued"] == 1
        due.refresh_from_db()
        later.refresh_from_db()
        assert due.blocked_at is None and due.retry_at is None
        assert later.blocked_at is not None
        assert list(bugs.agent_queue()) == [due]

    @pytest.mark.django_db
    def test_nobody_is_mailed_to_unblock_it(self):
        from plane.utils.agent_pipeline import notify

        assert not hasattr(notify, "admins_bug_blocked")


@pytest.mark.contract
class TestQuestionsAndSpecs:
    @pytest.mark.django_db
    def test_an_answered_question_reruns_the_analysis(self, agent_on, fire):
        from plane.bgtasks.agent_pipeline_task import feature_run_sweep

        f = feature(
            status=S.NEEDS_INFO,
            spec_runs=MAX_SPEC_RUNS,
            comments=[{"role": "agent", "text": "¿Para quién?"}, {"role": "user", "text": "Para ventas"}],
        )
        assert feature_run_sweep()["asked"] == 1
        f.refresh_from_db()
        assert f.status == S.SPEC_RUNNING
        assert "contestó" in fire["feature"].call_args.args[2]

    @pytest.mark.django_db
    def test_an_unanswered_question_reruns_with_assumptions_after_3_days(self, agent_on, fire):
        from plane.bgtasks.agent_pipeline_task import feature_run_sweep

        f = feature(status=S.NEEDS_INFO, comments=[{"role": "agent", "text": "¿Para quién?"}])
        assert feature_run_sweep()["asked"] == 0
        FeatureRequest.objects.filter(id=f.id).update(updated_at=timezone.now() - timedelta(days=4))
        assert feature_run_sweep()["asked"] == 1
        assert "supuestos" in fire["feature"].call_args.args[2]

    @pytest.mark.django_db
    def test_a_spec_past_its_cap_goes_back_after_a_growing_wait(self, agent_on, fire):
        from plane.bgtasks.agent_pipeline_task import feature_run_sweep

        recent = timezone.now() - timedelta(hours=2)
        f = feature(status=S.SUBMITTED, spec_runs=MAX_SPEC_RUNS, spec_requested_at=recent)
        assert feature_run_sweep()["retried"] == 0
        FeatureRequest.objects.filter(id=f.id).update(spec_requested_at=timezone.now() - timedelta(days=2))
        assert feature_run_sweep()["retried"] == 1
        f.refresh_from_db()
        assert f.status == S.SPEC_RUNNING and f.spec_runs == MAX_SPEC_RUNS + 1
