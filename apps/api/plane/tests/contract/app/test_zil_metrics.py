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
    Page,
    PageVersion,
    State,
    UsageDay,
    User,
    WorkspaceMember,
)
from plane.middleware.usage import classify
from plane.utils.zil_metrics import TZ, compute_person_metrics, compute_workspace_metrics

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


def activity(issue, actor, when, old, new, field="state"):
    # like Plane, a state change stores the names and the ids of both states
    states = (
        {s.name: s.id for s in State.all_state_objects.filter(project_id=issue.project_id)} if field == "state" else {}
    )
    act = IssueActivity.objects.create(
        issue=issue,
        project_id=issue.project_id,
        workspace_id=issue.workspace_id,
        actor=actor,
        verb="updated",
        field=field,
        old_value=old,
        new_value=new,
        old_identifier=states.get(old),
        new_identifier=states.get(new),
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
        # Plane logs every comment twice (IssueComment + IssueActivity field "comment"): counted once
        activity(done, designer, at(5, 14), None, "x", field="comment")
        # open, unassigned, untouched since Oct 1: stale at the end of the window
        make_issue(project, create_user, "Pendiente", at(1, 9))
        # outside the window: created later
        make_issue(project, create_user, "Futuro", at(20, 9))
        # Plane's onboarding demo item: never counted
        seed_bot = User.objects.create(email="seed@plane.test", username="seed", is_bot=True, bot_type="WORKSPACE_SEED")
        make_issue(project, seed_bot, "1. Welcome to Plane", at(2, 9))

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
        # 2 state changes + 2 comments, the comment's activity twin not counted
        assert sum(map(sum, m["usage"]["heatmap"])) == 4
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
    def test_intake_requests_are_not_work(self, workspace, project, create_user):
        # a pending or declined intake request stays in the triage state
        triage = State.triage_objects.get(project_id=project["id"])
        request = Issue.objects.create(name="Pedido de cliente", project_id=project["id"], state=triage)
        Issue.objects.filter(pk=request.pk).update(created_at=at(5, 9), created_by_id=create_user.id)
        make_issue(project, create_user, "Pieza", at(5, 10))

        m = compute_workspace_metrics(workspace, date(2026, 10, 1), date(2026, 10, 17))
        assert (m["flow"]["created"], m["flow"]["open"], m["flow"]["open_unassigned"]) == (1, 1, 1)
        assert [x["name"] for x in m["items"]["unassigned"]] == ["Pieza"]

    @pytest.mark.django_db
    def test_state_history_is_read_by_state_id(self, workspace, project, create_user):
        done = make_issue(project, create_user, "Carrusel", at(5, 10), at(7, 10), "completed")
        activity(done, create_user, at(6, 10), "Backlog", "In Progress")
        activity(done, create_user, at(7, 10), "In Progress", "Done")
        activity(done, create_user, at(8, 10), "Done", "In Progress")  # reopened
        activity(done, create_user, at(9, 10), "In Progress", "Done")
        Issue.objects.filter(pk=done.pk).update(completed_at=at(9, 10))
        # the team renames its states afterwards: the history still means the same
        State.objects.filter(project_id=project["id"], name="In Progress").update(name="En curso")
        State.objects.filter(project_id=project["id"], name="Done").update(name="Listo")

        flow = compute_workspace_metrics(workspace, date(2026, 10, 1), date(2026, 10, 17))["flow"]
        assert flow["cycle_time_hours"]["median"] == 72.0 and flow["completed_without_start"] == 0
        assert flow["reopen_events"] == 1
        person = compute_person_metrics(workspace, create_user, date(2026, 10, 1), date(2026, 10, 17))
        assert person["kinds"] == {"started": 2, "completed": 2}

    @pytest.mark.django_db
    def test_item_created_already_done_has_zero_lead_time(self, workspace, project, create_user):
        # Issue.save stamps completed_at a few ms before the insert sets created_at
        make_issue(project, create_user, "Hecho", at(5, 10), at(5, 10) - timedelta(milliseconds=3), "completed")
        flow = compute_workspace_metrics(workspace, date(2026, 10, 1), date(2026, 10, 17))["flow"]
        assert flow["completed"] == 1 and (flow["lead_time_hours"]["n"], flow["lead_time_hours"]["median"]) == (1, 0.0)

    @pytest.mark.django_db
    def test_bot_comment_is_one_bot_action(self, workspace, project, create_user):
        agent = User.objects.create(email="ada.agent@zil.test", username="ada", is_bot=True, bot_type="ZIL_AGENT")
        WorkspaceMember.objects.create(workspace=workspace, member=agent, role=15)
        item = make_issue(project, create_user, "Pieza", at(5, 10))
        comment(item, agent, at(5, 11))
        activity(item, agent, at(5, 11), None, "x", field="comment")  # Plane's twin of the comment

        m = compute_workspace_metrics(workspace, date(2026, 10, 1), date(2026, 10, 17))
        assert m["usage"]["bot_actions"] == 1

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


@pytest.mark.contract
class TestPersonMetrics:
    @pytest.mark.django_db
    def test_hours_active_time_work_and_debts(self, workspace, project, create_user):
        designer = User.objects.create(email="designer@zil.test", username="designer", display_name="Joaquin")
        WorkspaceMember.objects.create(workspace=workspace, member=designer, role=15)

        done = make_issue(project, create_user, "Carrusel", at(5, 10), at(7, 10), "completed", date(2026, 10, 8))
        assignment = IssueAssignee.objects.create(
            issue=done, assignee=designer, project_id=project["id"], workspace_id=workspace.id
        )
        IssueAssignee.objects.filter(pk=assignment.pk).update(created_at=at(5, 12))
        comment(done, create_user, at(5, 11))
        comment(done, designer, at(5, 14))  # Monday 14:00, answers 3 h later
        activity(done, designer, at(5, 14), None, "x", field="comment")  # twin of the comment: skipped
        activity(done, designer, at(6, 10), "Backlog", "In Progress")  # starts 22 h after assignment
        activity(done, designer, at(7, 10), "In Progress", "Done")  # Wednesday 10:00
        activity(done, designer, datetime(2026, 10, 7, 10, 10, tzinfo=TZ), "Carrusel", "Carrusel v2", field="name")
        page = Page.objects.create(name="Brief ACME", workspace=workspace, owned_by=designer)
        PageVersion.objects.create(
            workspace=workspace, page=page, owned_by=designer, last_saved_at=datetime(2026, 10, 7, 10, 20, tzinfo=TZ)
        )
        Notification.objects.create(
            workspace=workspace,
            project_id=project["id"],
            receiver=designer,
            sender="in_app:issue_activities:assigned",
            entity_name="issue",
            entity_identifier=done.id,
            title="t",
            read_at=at(5, 16),
        )
        Notification.objects.filter(receiver=designer).update(created_at=at(5, 12))
        owed = make_issue(project, create_user, "Pendiente", at(1, 9))
        IssueAssignee.objects.create(issue=owed, assignee=designer, project_id=project["id"], workspace_id=workspace.id)

        m = compute_person_metrics(workspace, designer, date(2026, 10, 1), date(2026, 10, 17))
        totals, rhythm, work = m["totals"], m["rhythm"], m["work"]
        assert m["person"]["name"] == "Joaquin"
        assert m["kinds"] == {"comment": 1, "started": 1, "completed": 1, "edited": 1, "page": 1}
        assert (totals["actions"], totals["action_days"], totals["comments"], totals["page_saves"]) == (5, 3, 1, 1)
        # Mon: 14:00 comment + 16:00 read = two 5-min sessions; Tue: 10:00 = 5 min; Wed: 10:00-10:20 = 25 min
        assert (totals["active_minutes"], totals["sessions"], totals["active_minutes_per_day"]) == (40, 4, 10)
        oct5 = next(d for d in m["daily"] if d["date"] == "2026-10-05")
        assert (oct5["first"], oct5["last"], oct5["active_minutes"]) == ("14:00", "16:00", 10)
        assert rhythm["first_hour_median"] == 10.0 and rhythm["completion_hour_median"] == 10.0
        assert m["heatmap"][0][14] == 1 and m["heatmap"][0][16] == 1  # the read counts as presence
        assert m["heatmap_completed"][2][10] == 1
        assert work["completed_assigned"] == 1 and work["lead_time_median_hours"] == 48.0
        assert work["start_after_assignment_median_hours"] == 22.0 and work["on_time_rate"] == 1.0
        assert work["reply_median_hours"] == 3.0 and work["notifications_read"] == 1
        assert (work["open_assigned"], work["open_stale"]) == (1, 1) and m["owed"][0]["name"] == "Pendiente"
        assert m["timeline"][0]["kind"] == "page" and m["timeline"][-1]["kind"] == "comment"
        assert m["projects"][0]["actions"] == 4 and len(m["daily"]) == 16

    @pytest.mark.django_db
    def test_mark_all_read_is_one_moment(self, workspace, project, create_user):
        designer = User.objects.create(email="designer@zil.test", username="designer", display_name="Joaquin")
        WorkspaceMember.objects.create(workspace=workspace, member=designer, role=15)
        item = make_issue(project, create_user, "Pieza", at(5, 10))
        Notification.objects.bulk_create(
            Notification(
                workspace=workspace,
                project_id=project["id"],
                receiver=designer,
                sender="in_app:issue_activities:assigned",
                entity_name="issue",
                entity_identifier=item.id,
                title="t",
                # Plane's "mark all as read" stamps each one in a loop: same second, different microseconds
                read_at=at(6, 9) + timedelta(microseconds=n * 900),
            )
            for n in range(120)
        )
        Notification.objects.filter(receiver=designer).update(created_at=at(5, 12))

        m = compute_person_metrics(workspace, designer, date(2026, 10, 1), date(2026, 10, 17))
        assert sum(map(sum, m["heatmap"])) == 1 and m["heatmap"][1][9] == 1
        assert (m["totals"]["sessions"], m["work"]["notifications_read"]) == (1, 120)

    @pytest.mark.django_db
    def test_intake_request_is_not_owed(self, workspace, project, create_user):
        triage = State.triage_objects.get(project_id=project["id"])
        request = Issue.objects.create(name="Pedido de cliente", project_id=project["id"], state=triage)
        owed = make_issue(project, create_user, "Pieza", at(5, 10))
        for issue in (request, owed):
            IssueAssignee.objects.create(
                issue=issue, assignee=create_user, project_id=project["id"], workspace_id=workspace.id
            )

        m = compute_person_metrics(workspace, create_user, date(2026, 10, 1), date(2026, 10, 17))
        assert [o["name"] for o in m["owed"]] == ["Pieza"] and m["work"]["open_assigned"] == 1

    @pytest.mark.django_db
    def test_endpoint_only_for_members(self, api_client, workspace, create_user):
        url = "/api/zil/sync/metrics/person/"
        api_client.credentials(HTTP_X_ZIL_SERVICE_KEY="secret")
        missing = api_client.get(url, {"workspace_slug": workspace.slug, "email": "nobody@zil.test"})
        assert missing.status_code == status.HTTP_404_NOT_FOUND
        ok = api_client.get(
            url,
            {
                "workspace_slug": workspace.slug,
                "email": create_user.email.upper(),
                "since": "2026-10-01",
                "until": "2026-10-08",
            },
        )
        assert ok.status_code == status.HTTP_200_OK and len(ok.data["daily"]) == 7
