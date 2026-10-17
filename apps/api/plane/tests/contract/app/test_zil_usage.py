# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import threading
from datetime import date, datetime, timezone as dt_timezone
from unittest import mock

import pytest
from django.db import connection, connections
from django.test import Client
from django.test.utils import CaptureQueriesContext
from rest_framework import status
from rest_framework.test import APIClient

from plane.db.models import UsageDay, User
from plane.middleware.usage import UsageTrackingMiddleware, classify


def usage_queries(ctx):
    return [q for q in ctx.captured_queries if "usage_days" in q["sql"]]


def fake_request(user, path="/api/workspaces/zil/projects/p/pages/", method="GET"):
    return mock.Mock(method=method, path=path, META={}, user=user)


@pytest.fixture
def project(session_client, workspace):
    response = session_client.post(
        f"/api/workspaces/{workspace.slug}/projects/", {"name": "Estudio", "identifier": "EST"}, format="json"
    )
    assert response.status_code == status.HTTP_201_CREATED
    return response.data


@pytest.mark.contract
class TestUsageHotPath:
    @pytest.mark.django_db
    def test_one_upsert_per_counted_request_and_none_elsewhere(self, session_client, workspace):
        with CaptureQueriesContext(connection) as ctx:
            assert session_client.get(f"/api/workspaces/{workspace.slug}/invitations/").status_code == 200
        assert len(usage_queries(ctx)) == 1
        with CaptureQueriesContext(connection) as ctx:
            assert session_client.get("/api/users/me/").status_code == 200
        assert usage_queries(ctx) == []

    @pytest.mark.django_db(transaction=True)
    def test_concurrent_requests_on_the_same_row_lose_no_counts(self):
        user = User.objects.create(email="concurrent@zil.test", username="concurrent")
        middleware = UsageTrackingMiddleware(lambda request: None)
        barrier = threading.Barrier(16)
        errors = []

        def worker():
            try:
                barrier.wait()
                for _ in range(25):
                    middleware.count(fake_request(user))
            finally:
                connections.close_all()

        with mock.patch("plane.middleware.usage.log_exception", side_effect=errors.append):
            threads = [threading.Thread(target=worker) for _ in range(16)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        assert errors == []
        assert list(UsageDay.objects.filter(user=user).values_list("reads", "writes")) == [(400, 0)]

    @pytest.mark.django_db
    def test_a_failed_count_is_logged_and_the_request_still_succeeds(self, session_client, workspace):
        broken = mock.Mock()
        broken.cursor.side_effect = RuntimeError("db down")
        with (
            mock.patch("plane.middleware.usage.connection", broken),
            mock.patch("plane.middleware.usage.log_exception") as log,
        ):
            response = session_client.get(f"/api/workspaces/{workspace.slug}/invitations/")
        assert response.status_code == status.HTTP_200_OK
        log.assert_called_once()

    @pytest.mark.django_db
    def test_the_day_is_the_argentina_day(self, create_user):
        middleware = UsageTrackingMiddleware(lambda request: None)
        # 23:30 ART on the 16th, then 00:30 ART on the 17th
        for utc in (
            datetime(2026, 10, 17, 2, 30, tzinfo=dt_timezone.utc),
            datetime(2026, 10, 17, 3, 30, tzinfo=dt_timezone.utc),
        ):
            with mock.patch("plane.middleware.usage.timezone.now", return_value=utc):
                middleware.count(fake_request(create_user))
        assert sorted(UsageDay.objects.filter(user=create_user).values_list("date", flat=True)) == [
            date(2026, 10, 16),
            date(2026, 10, 17),
        ]


@pytest.mark.contract
class TestUsageChannelsAndPeople:
    @pytest.mark.django_db
    def test_a_real_browser_session_counts_as_web(self, create_user, workspace):
        browser = Client()
        browser.force_login(create_user)
        assert browser.get(f"/api/workspaces/{workspace.slug}/invitations/").status_code == 200
        row = UsageDay.objects.get(user=create_user)
        assert (row.workspace_slug, row.surface, row.channel, row.reads) == (workspace.slug, "members", "web", 1)

    @pytest.mark.django_db
    def test_api_key_requests_count_as_api(self, api_key_client, workspace, create_user):
        assert api_key_client.get(f"/api/v1/workspaces/{workspace.slug}/projects/").status_code == 200
        row = UsageDay.objects.get(user=create_user)
        assert (row.surface, row.channel) == ("projects", "api")

    @pytest.mark.django_db
    def test_anonymous_and_failed_requests_are_not_counted(self, session_client, workspace):
        anonymous = APIClient()
        assert anonymous.get(f"/api/workspaces/{workspace.slug}/invitations/").status_code in (401, 403)
        assert anonymous.get("/").status_code == 200
        assert session_client.get(f"/api/workspaces/{workspace.slug}/projects/{workspace.id}/").status_code >= 400
        assert not UsageDay.objects.exists()


@pytest.mark.contract
class TestUsageSurfaces:
    @pytest.mark.django_db
    def test_opening_a_project_is_not_using_cycles_modules_views_members_or_intake(
        self, session_client, workspace, project, create_user
    ):
        # the requests web's workspace-wrapper and project-wrapper fire on every open
        ws = f"/api/workspaces/{workspace.slug}"
        pr = f"{ws}/projects/{project['id']}"
        for url in (f"{ws}/members/", f"{ws}/modules/", f"{ws}/cycles/", f"{pr}/members/", f"{pr}/cycles/"):
            assert session_client.get(url).status_code == 200, url
        for url in (f"{pr}/modules/", f"{pr}/views/", f"{pr}/intake-state/"):
            session_client.get(url)

        surfaces = set(UsageDay.objects.filter(user=create_user).values_list("surface", flat=True))
        assert surfaces <= {"projects", "other"}

    def test_shell_lists_vs_real_use(self):
        ws = "/api/workspaces/zil"
        pr = f"{ws}/projects/p"
        shell = [f"{pr}/members/", f"{pr}/cycles/", f"{pr}/modules/", f"{pr}/views/", f"{pr}/intake-state/"]
        assert {classify(url)[1] for url in shell} == {"projects"}
        assert {classify(f"{ws}/{name}/")[1] for name in ("members", "cycles", "modules")} == {"other"}
        # the same collections are real use when written to, opened, or listed by an agent
        assert classify(f"{pr}/cycles/", "POST")[1] == "cycles"
        assert classify(f"{pr}/cycles/c/cycle-issues/")[1] == "cycles"
        assert classify(f"{pr}/modules/m/")[1] == "modules"
        assert classify(f"{pr}/views/v/")[1] == "views"
        assert classify(f"{ws}/views/")[1] == "views"
        assert classify(f"{pr}/members/m/", "PATCH")[1] == "members"
        assert classify(f"{ws}/invitations/")[1] == "members"
        assert classify(f"{pr}/intake-issues/")[1] == "intake"
        assert classify("/api/v1/workspaces/zil/projects/p/cycles/")[1] == "cycles"

    def test_analytics_and_work_item_routes(self):
        ws = "/api/workspaces/zil"
        pr = f"{ws}/projects/p"
        for url in (
            f"{ws}/advance-analytics/",
            f"{ws}/advance-analytics-charts/",
            f"{pr}/advance-analytics-stats/",
            f"{ws}/default-analytics/",
            f"{ws}/analytic-view/",
            f"{ws}/analytics/",
        ):
            assert classify(url)[1] == "analytics", url
        assert classify(f"{pr}/cycles/c/analytics/")[1] == "cycles"
        for url in (
            f"{pr}/archived-issues/",
            f"{pr}/deleted-issues/",
            f"{pr}/bulk-delete-issues/",
            f"{pr}/bulk-archive-issues/",
            f"{pr}/issue-dates/",
            f"{ws}/draft-issues/",
            f"{ws}/draft-to-issue/d/",
            f"{ws}/user-issues/u/",
        ):
            assert classify(url, "POST")[1] == "work_items", url
        # the archive pages and the favorite stars of cycles and modules are cycles / modules use
        for url, surface in (
            (f"{pr}/archived-cycles/", "cycles"),
            (f"{pr}/archived-cycles/c/", "cycles"),
            (f"{pr}/user-favorite-cycles/", "cycles"),
            (f"{pr}/archived-modules/", "modules"),
            (f"{pr}/archived-modules/m/", "modules"),
            (f"{pr}/user-favorite-modules/", "modules"),
            ("/api/v1/workspaces/zil/projects/p/archived-cycles/", "cycles"),
        ):
            assert classify(url)[1] == surface, url
        assert classify(f"{pr}/issue-labels/")[1] == "projects"
        assert classify(f"{pr}/search-issues/")[1] == "search"
        assert classify(f"{pr}/intake-issues/")[1] == "intake"
