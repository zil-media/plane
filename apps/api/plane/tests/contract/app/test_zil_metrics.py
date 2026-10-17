# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from datetime import date, datetime, timedelta
from unittest import mock

import pytest
from rest_framework import status

from plane.db.models import (
    Module,
    ModuleIssue,
    Issue,
    IssueActivity,
    IssueAssignee,
    IssueComment,
    Notification,
    State,
    UsageDay,
    User,
    WorkspaceMember,
)
from plane.middleware.usage import classify
from plane.utils.zil_metrics import TZ, compute_workspace_metrics

ZIL_ENV = {"ZIL_BASE_URL": "http://zil.test", "ZIL_SERVICE_SECRET": "secret"}


@pytest.fixture(autouse=True)
def no_background_tasks():
    with (
        mock.patch("plane.app.views.page.base.page_transaction.delay"),
        mock.patch("plane.app.views.page.base.recent_visited_task.delay"),
        mock.patch.dict("os.environ", ZIL_ENV),
    ):
        yield


@pytest.fixture
def project(session_client, workspace):
    response = session_client.post(
        f"/api/workspaces/{workspace.slug}/projects/", {"name": "Estudio", "identifier": "EST"}, format="json"
    )
    assert response.status_code == status.HTTP_201_CREATED
    return response.data


def at(day, hour):
    return datetime(2026, 10, day, hour, 0, tzinfo=TZ)


def make_issue(project, user, name, created, completed=None, state_group="backlog", target=None, description=""):
    state = State.objects.filter(project_id=project["id"], group=state_group).first()
    issue = Issue.objects.create(
        name=name, project_id=project["id"], state=state, target_date=target, description_html=f"<p>{description}</p>"
    )
    Issue.objects.filter(pk=issue.pk).update(created_at=created, completed_at=completed, created_by_id=user.id)
    return Issue.objects.get(pk=issue.pk)


def activity(issue, actor, when, old, new):
    act = IssueActivity.objects.create(
        issue=issue,
        project_id=issue.project_id,
        workspace_id=issue.workspace_id,
        actor=actor,
        verb="updated",
        field="state",
        old_value=old,
        new_value=new,
    )
    IssueActivity.objects.filter(pk=act.pk).update(created_at=when)


def comment(issue, actor, when):
    c = IssueComment.objects.create(
        issue=issue, project_id=issue.project_id, workspace_id=issue.workspace_id, actor=actor, comment_html="<p>x</p>"
    )
    IssueComment.objects.filter(pk=c.pk).update(created_at=when)


@pytest.mark.contract
class TestUsageTracking:
    def test_classify_paths(self):
        assert classify("/api/workspaces/zil/projects/p/pages/") == ("zil", "pages")
        assert classify("/api/workspaces/zil/projects/p/issues/i/comments/") == ("zil", "work_items")
        assert classify("/api/workspaces/zil/projects/p/pages/x/zil-client/profile/") == ("zil", "client_profile")
        assert classify("/api/v1/workspaces/zil/projects/p/work-items/") == ("zil", "work_items")
        assert classify("/api/workspaces/zil/users/notifications/unread/") is None
        assert classify("/api/users/me/") is None

    @pytest.mark.django_db
    def test_requests_are_counted_per_day_surface_and_kind(self, session_client, workspace, project, create_user):
        pages_url = f"/api/workspaces/{workspace.slug}/projects/{project['id']}/pages/"
        assert session_client.get(pages_url).status_code == status.HTTP_200_OK
        session_client.get(pages_url)
        assert session_client.post(pages_url, {"name": "Brief"}, format="json").status_code == status.HTTP_201_CREATED
        session_client.get(f"/api/workspaces/{workspace.slug}/projects/{project['id']}/pages/{project['id']}/")  # 404

        row = UsageDay.objects.get(user=create_user, workspace_slug=workspace.slug, surface="pages")
        assert (row.reads, row.writes, row.channel) == (2, 1, "web")


@pytest.mark.contract
class TestWorkspaceMetrics:
    @pytest.mark.django_db
    def test_flow_interactions_and_people(self, workspace, project, create_user):
        designer = User.objects.create(email="designer@zil.test", username="designer", display_name="Joaquin")
        WorkspaceMember.objects.create(workspace=workspace, member=designer, role=15)

        # done in 2 days, started after 1 day, on time, designer replied 3 h after the brief
        done = make_issue(
            project, create_user, "Carrusel", at(5, 10), at(7, 10), "completed", date(2026, 10, 8), "x" * 60
        )
        IssueAssignee.objects.create(issue=done, assignee=designer, project_id=project["id"], workspace_id=workspace.id)
        activity(done, designer, at(6, 10), "Backlog", "In Progress")
        activity(done, designer, at(7, 10), "In Progress", "Done")
        module = Module.objects.create(name="ACME", project_id=project["id"])
        ModuleIssue.objects.create(module=module, issue=done, project_id=project["id"], workspace_id=workspace.id)
        comment(done, create_user, at(5, 11))
        comment(done, designer, at(5, 14))
        # open, unassigned, untouched since Oct 1: stale at the end of the window
        make_issue(project, create_user, "Pendiente", at(1, 9))
        # outside the window: created later
        make_issue(project, create_user, "Futuro", at(20, 9))

        Notification.objects.create(
            workspace=workspace,
            project_id=project["id"],
            receiver=designer,
            sender="in_app:issue_activities:mentioned",
            entity_name="issue",
            entity_identifier=done.id,
            title="t",
            read_at=at(5, 16),
        )
        Notification.objects.filter(receiver=designer).update(created_at=at(5, 14))
        Notification.objects.create(
            workspace=workspace,
            project_id=project["id"],
            receiver=designer,
            sender="in_app:issue_activities:assigned",
            entity_name="issue",
            entity_identifier=done.id,
            title="t",
        )
        Notification.objects.filter(receiver=designer, read_at__isnull=True).update(created_at=at(6, 9))

        m = compute_workspace_metrics(workspace, date(2026, 10, 1), date(2026, 10, 17))
        flow, inter = m["flow"], m["interactions"]
        assert (flow["created"], flow["completed"]) == (2, 1)
        assert flow["lead_time_hours"]["median"] == 48.0
        assert flow["cycle_time_hours"]["median"] == 24.0
        assert flow["time_to_first_reply_hours"]["median"] == 4.0
        assert flow["on_time_rate"] == 1.0
        assert (flow["open"], flow["open_stale"], flow["open_unassigned"]) == (1, 1, 1)
        assert inter["comments"] == 2 and inter["reply_latency_hours"]["median"] == 3.0
        assert inter["mentions"] == 1 and inter["notifications_read_rate"] == 0.5
        assert inter["time_to_read_hours"]["median"] == 2.0

        # weekly series covers the window, Monday-based
        assert sum(w["completed"] for w in flow["weekly"]) == 1 and flow["weekly"][0]["week"] == "2026-09-28"
        # time spent in each state before leaving it: Backlog 1 day, In Progress 1 day
        in_progress = next(s for s in flow["state_time"] if s["state"] == "In Progress")
        assert in_progress["median_hours"] == 24.0 and in_progress["group"] == "started"
        assert sum(b["open"] for b in flow["aging"]) == 1
        # reply pairs and heatmap (Oct 5 2026 is a Monday)
        assert inter["reply_pairs"][0]["replies"] == 1 and inter["reply_pairs"][0]["median_hours"] == 3.0
        assert m["usage"]["heatmap"][0][11] >= 1
        # per client, from the module the item is in
        acme = next(c for c in m["clients"] if c["name"] == "ACME")
        assert (acme["completed"], acme["comments"], acme["lead_time_median_hours"]) == (1, 2, 48.0)
        # items to act on
        assert [x["name"] for x in m["items"]["stale"]] == ["Pendiente"]
        assert [x["name"] for x in m["items"]["unassigned"]] == ["Pendiente"]

        joaquin = next(p for p in m["people"] if p["name"] == "Joaquin")
        assert joaquin["reply_median_hours"] == 3.0 and joaquin["on_time_rate"] == 1.0
        assert joaquin["action_days"] == 3 and joaquin["lead_time_median_hours"] == 48.0
        assert (joaquin["completed_assigned"], joaquin["comments"], joaquin["notifications_read"]) == (1, 1, 1)

    @pytest.mark.django_db
    def test_endpoint_needs_the_service_key_and_a_valid_window(self, api_client, workspace):
        url = "/api/zil/sync/metrics/"
        assert api_client.get(url, {"workspace_slug": workspace.slug}).status_code in (401, 403)
        api_client.credentials(HTTP_X_ZIL_SERVICE_KEY="secret")
        assert api_client.get(url, {"workspace_slug": "nope"}).status_code == status.HTTP_404_NOT_FOUND
        bad = api_client.get(url, {"workspace_slug": workspace.slug, "since": "2026-10-10", "until": "2026-10-01"})
        assert bad.status_code == status.HTTP_400_BAD_REQUEST
        ok = api_client.get(url, {"workspace_slug": workspace.slug, "since": "2026-09-01", "until": "2026-10-01"})
        assert ok.status_code == status.HTTP_200_OK
        assert set(ok.data) >= {"usage", "flow", "interactions", "projects", "people"}
        assert (date.fromisoformat(ok.data["until"]) - date.fromisoformat(ok.data["since"])) == timedelta(days=30)
