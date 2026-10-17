# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Counts, per person and day, which parts of Ops they use (UsageDay).

One upsert per successful workspace-scoped API request. Reads are GETs, writes are
POST/PATCH/PUT/DELETE. Polling endpoints (unread counters) are not counted, so a
tab left open doesn't look like use. A failed count is logged and never breaks the
request it measures.
"""

import re
import uuid
from zoneinfo import ZoneInfo

from django.db import connection
from django.utils import timezone

from plane.utils.exception_logger import log_exception

WORKSPACE_PATH = re.compile(r"^/api/(?P<v1>v1/)?workspaces/(?P<slug>[^/]+)/(?P<rest>.*)$")
# the team works on Argentina time: a day of use is an ART day
USAGE_TZ = ZoneInfo("America/Argentina/Buenos_Aires")
WRITE_METHODS = {"POST", "PATCH", "PUT", "DELETE"}
# unread counters and similar background polls
IGNORED = re.compile(r"(unread|/notifications/count|/user-favorites/?$|/users/me/)")
# lists the web app loads on every workspace / project open to fill its pickers and
# sidebar (project-wrapper, workspace-wrapper, use-workspace-issue-properties): they
# mean "opened the project", not "used cycles / modules / views / members / intake".
# The workspace's own views/ list is the Views page itself, so it stays a visit.
SHELL_LISTS = re.compile(r"^(?P<project>/projects/[^/]+)?/(?P<list>members|cycles|modules|views|intake-state)/$")

# first match wins: the more specific parts of the path go first
SURFACE_RULES = (
    ("client_profile", re.compile(r"/zil-client|/zil-clients")),
    ("intake", re.compile(r"/intake|/inbox-issues")),
    ("support", re.compile(r"/support|/bug-reports|/feature-requests")),
    ("notifications", re.compile(r"/notifications")),
    ("pages", re.compile(r"/pages")),
    # also archived-cycles / archived-modules (their archive pages) and user-favorite-*
    ("cycles", re.compile(r"/cycles|-cycles/")),
    ("modules", re.compile(r"/modules|-modules/")),
    ("views", re.compile(r"/views")),
    ("search", re.compile(r"/search")),
    # analytics, advance-analytics(-stats|-charts), default-analytics, analytic-view, export-analytics
    ("analytics", re.compile(r"analytic")),
    # also archived-, deleted-, draft-, user-, bulk-*-issues and the timeline's issue-dates
    ("work_items", re.compile(r"/issues|-issues/|/issue-dates|/draft-to-issue|/work-items|/comments")),
    ("members", re.compile(r"/members|/invitations")),
    ("projects", re.compile(r"/projects")),
)

UPSERT = """
INSERT INTO usage_days (id, date, user_id, workspace_slug, surface, channel, reads, writes, first_at, last_at)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (date, user_id, workspace_slug, surface, channel)
DO UPDATE SET reads = usage_days.reads + EXCLUDED.reads,
              writes = usage_days.writes + EXCLUDED.writes,
              last_at = EXCLUDED.last_at
"""


def classify(path, method="GET"):
    """(workspace_slug, surface) for a workspace-scoped API path, else None."""
    match = WORKSPACE_PATH.match(path)
    if not match or IGNORED.search(path):
        return None
    rest = "/" + match.group("rest")
    shell = SHELL_LISTS.match(rest) if method == "GET" and not match.group("v1") else None
    if shell and (shell.group("project") or shell.group("list") != "views"):
        surface = "projects" if shell.group("project") else "other"
    else:
        surface = next((name for name, rule in SURFACE_RULES if rule.search(rest)), "other")
    return match.group("slug")[:48], surface


class UsageTrackingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.method in ("GET", "POST", "PATCH", "PUT", "DELETE") and response.status_code < 400:
            self.count(request)
        return response

    def count(self, request):
        user = getattr(request, "user", None)
        if user is None or not getattr(user, "is_authenticated", False):
            return
        classified = classify(request.path, request.method)
        if classified is None:
            return
        slug, surface = classified
        is_write = request.method in WRITE_METHODS
        channel = "api" if (request.path.startswith("/api/v1/") or "HTTP_X_API_KEY" in request.META) else "web"
        now = timezone.now()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    UPSERT,
                    [
                        str(uuid.uuid4()),
                        timezone.localtime(now, USAGE_TZ).date(),
                        str(user.id),
                        slug,
                        surface,
                        channel,
                        0 if is_write else 1,
                        1 if is_write else 0,
                        now,
                        now,
                    ],
                )
        except Exception as e:
            log_exception(e)
