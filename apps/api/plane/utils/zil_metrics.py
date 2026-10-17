# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Usage, interaction and timing metrics of one workspace over a window of days.

Read by Zil Workspace (GET /api/zil/sync/metrics/), which snapshots them daily and
shows them in Gestión Ops. Days are Argentina days; `until` is exclusive. People are
the workspace's human members; bots (AI agents, the Zil service user) are counted apart.

Open-work figures are taken at the END of the window from creation/completion dates,
so a past window gives a fair picture without replaying every state change.
"""

# Python imports
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, time, timedelta
from statistics import median
from zoneinfo import ZoneInfo

# Module imports
from plane.db.models import (
    EmailNotificationLog,
    Issue,
    IssueActivity,
    IssueAssignee,
    IssueComment,
    ModuleIssue,
    Notification,
    Page,
    State,
    UsageDay,
    WorkspaceMember,
)

TZ = ZoneInfo("America/Argentina/Buenos_Aires")
STALE_DAYS = 14
READY_MIN_DESCRIPTION = 50
DONE_GROUPS = {"completed", "cancelled"}
LIST_LIMIT = 30
AGE_BUCKETS = (("0-7 d", 0, 7), ("8-14 d", 8, 14), ("15-30 d", 15, 30), ("31-60 d", 31, 60), ("60+ d", 61, None))


def _hours(delta):
    return delta.total_seconds() / 3600


def _stats(values):
    """median / p75 / p90 in hours, rounded; None when there is nothing to measure."""
    values = sorted(v for v in values if v is not None and v >= 0)
    if not values:
        return {"n": 0, "median": None, "p75": None, "p90": None}

    def pct(p):
        return round(values[min(len(values) - 1, int(round(p * (len(values) - 1))))], 1)

    return {"n": len(values), "median": round(median(values), 1), "p75": pct(0.75), "p90": pct(0.9)}


def _median(values):
    values = [v for v in values if v is not None and v >= 0]
    return round(median(values), 1) if values else None


def _rate(num, den):
    return round(num / den, 3) if den else None


def _client_key(name):
    """Module names spelled differently across projects ("GEN-IT", "Gen It") are one client."""
    return re.sub(r"[^a-z0-9]", "", (name or "").casefold())


def _person_name(user):
    return user.display_name or f"{user.first_name} {user.last_name}".strip() or user.email


def compute_workspace_metrics(workspace, since, until):
    start = datetime.combine(since, time.min, TZ)
    end = datetime.combine(until, time.min, TZ)
    stale_cutoff = end - timedelta(days=STALE_DAYS)
    end_date = until - timedelta(days=1)
    web_url = (os.environ.get("WEB_URL") or "").rstrip("/")

    def in_window(ts):
        return ts is not None and start <= ts < end

    # ── people ───────────────────────────────────────────────────────────────
    members = {
        m.member_id: m.member
        for m in WorkspaceMember.objects.filter(workspace_id=workspace.id, is_active=True).select_related("member")
    }
    humans = {uid: u for uid, u in members.items() if not u.is_bot}
    bots = {uid for uid, u in members.items() if u.is_bot}
    names = {uid: _person_name(u) for uid, u in members.items()}

    # ── work items ───────────────────────────────────────────────────────────
    issues = list(
        Issue.objects.filter(workspace_id=workspace.id, is_draft=False, created_at__lt=end).values(
            "id",
            "name",
            "sequence_id",
            "project_id",
            "project__name",
            "project__identifier",
            "created_at",
            "created_by_id",
            "completed_at",
            "target_date",
            "state__name",
            "state__group",
            "archived_at",
            "description_stripped",
        )
    )
    issue_ids = [i["id"] for i in issues]
    issue_by_id = {i["id"]: i for i in issues}
    state_group = {
        (s["project_id"], s["name"]): s["group"]
        for s in State.objects.filter(workspace_id=workspace.id).values("project_id", "name", "group")
    }
    assignees = defaultdict(set)
    assigned_at = {}
    first_assigned = {}
    for a in IssueAssignee.objects.filter(issue_id__in=issue_ids).values("issue_id", "assignee_id", "created_at"):
        assignees[a["issue_id"]].add(a["assignee_id"])
        assigned_at[(a["issue_id"], a["assignee_id"])] = a["created_at"]
        if a["issue_id"] not in first_assigned or a["created_at"] < first_assigned[a["issue_id"]]:
            first_assigned[a["issue_id"]] = a["created_at"]

    modules_of = defaultdict(list)
    for mi in ModuleIssue.objects.filter(issue_id__in=issue_ids).values("issue_id", "module__name"):
        if mi["module__name"]:
            modules_of[mi["issue_id"]].append(mi["module__name"])

    activities = list(
        IssueActivity.objects.filter(issue_id__in=issue_ids, created_at__lt=end)
        .values("issue_id", "field", "old_value", "new_value", "actor_id", "created_at")
        .order_by("created_at")
    )
    last_touch = {}
    first_started = {}
    reopens = Counter()
    state_durations = defaultdict(list)
    last_state_change = {}
    for act in activities:
        iid = act["issue_id"]
        issue = issue_by_id[iid]
        last_touch[iid] = act["created_at"]
        if act["field"] != "state":
            continue
        project_id = issue["project_id"]
        new_group = state_group.get((project_id, act["new_value"]))
        old_group = state_group.get((project_id, act["old_value"]))
        if new_group == "started" and iid not in first_started:
            first_started[iid] = act["created_at"]
        if in_window(act["created_at"]):
            if old_group == "completed" and new_group not in DONE_GROUPS:
                reopens[iid] += 1
            # time spent in the state that is being left
            entered = last_state_change.get(iid, issue["created_at"])
            if act["old_value"]:
                state_durations[(act["old_value"], old_group or "")].append(_hours(act["created_at"] - entered))
        last_state_change[iid] = act["created_at"]

    comments = list(
        IssueComment.objects.filter(issue_id__in=issue_ids, created_at__lt=end)
        .values("issue_id", "actor_id", "created_at")
        .order_by("created_at")
    )
    for c in comments:
        last_touch[c["issue_id"]] = max(last_touch.get(c["issue_id"], c["created_at"]), c["created_at"])

    created = [i for i in issues if in_window(i["created_at"])]
    completed = [i for i in issues if in_window(i["completed_at"]) and i["state__group"] == "completed"]

    def is_open_at_end(i):
        if i["state__group"] == "cancelled" or (i["archived_at"] and i["completed_at"] is None):
            return False
        return i["completed_at"] is None or i["completed_at"] >= end

    open_items = [i for i in issues if is_open_at_end(i)]

    def touched(i):
        return max(last_touch.get(i["id"], i["created_at"]), i["created_at"])

    def is_stale(i):
        return touched(i) < stale_cutoff

    def is_overdue(i):
        return bool(i["target_date"]) and i["target_date"] < end_date

    def on_time(i):
        return i["completed_at"].astimezone(TZ).date() <= i["target_date"]

    dated_done = [i for i in completed if i["target_date"]]

    first_reply = {}
    for c in comments:
        issue = issue_by_id[c["issue_id"]]
        if c["actor_id"] != issue["created_by_id"] and c["issue_id"] not in first_reply:
            first_reply[c["issue_id"]] = c["created_at"]

    # weeks start on Monday (Argentina)
    week_of = lambda ts: (ts.astimezone(TZ).date() - timedelta(days=ts.astimezone(TZ).weekday()))  # noqa: E731
    weeks = Counter()
    weeks_done = Counter()
    first_week = since - timedelta(days=since.weekday())
    week = first_week
    while week < until:
        weeks[week] += 0
        weeks_done[week] += 0
        week += timedelta(days=7)
    for i in created:
        weeks[week_of(i["created_at"])] += 1
    for i in completed:
        weeks_done[week_of(i["completed_at"])] += 1

    aging = []
    for label, lo, hi in AGE_BUCKETS:
        count = 0
        for i in open_items:
            age = (end - i["created_at"]).days
            if age >= lo and (hi is None or age <= hi):
                count += 1
        aging.append({"bucket": label, "open": count})

    flow = {
        "created": len(created),
        "completed": len(completed),
        "cancelled": sum(1 for i in created if i["state__group"] == "cancelled"),
        "lead_time_hours": _stats(_hours(i["completed_at"] - i["created_at"]) for i in completed),
        "cycle_time_hours": _stats(
            _hours(i["completed_at"] - first_started[i["id"]]) for i in completed if i["id"] in first_started
        ),
        "time_to_first_assignment_hours": _stats(
            _hours(first_assigned[i["id"]] - i["created_at"]) for i in created if i["id"] in first_assigned
        ),
        "time_to_first_reply_hours": _stats(
            _hours(first_reply[i["id"]] - i["created_at"]) for i in created if i["id"] in first_reply
        ),
        "completed_without_start": sum(1 for i in completed if i["id"] not in first_started),
        "on_time_rate": _rate(sum(1 for i in dated_done if on_time(i)), len(dated_done)),
        "reopen_events": sum(reopens.values()),
        "ready_at_creation_rate": _rate(
            sum(
                1
                for i in created
                if assignees[i["id"]]
                and i["target_date"]
                and len((i["description_stripped"] or "").strip()) >= READY_MIN_DESCRIPTION
            ),
            len(created),
        ),
        "multi_assignee_rate": _rate(sum(1 for i in created if len(assignees[i["id"]]) > 1), len(created)),
        "open": len(open_items),
        "open_stale": sum(1 for i in open_items if is_stale(i)),
        "open_unassigned": sum(1 for i in open_items if not assignees[i["id"]]),
        "open_overdue": sum(1 for i in open_items if is_overdue(i)),
        "open_without_due_date": sum(1 for i in open_items if not i["target_date"]),
        "weekly": [{"week": w.isoformat(), "created": weeks[w], "completed": weeks_done[w]} for w in sorted(weeks)],
        "aging": aging,
        # where work waits: median time spent in each state before leaving it (transitions in the window)
        "state_time": sorted(
            (
                {"state": name, "group": group, "median_hours": _median(values), "n": len(values)}
                for (name, group), values in state_durations.items()
            ),
            key=lambda s: -(s["median_hours"] or 0),
        ),
    }

    projects = defaultdict(lambda: {"name": "", "created": 0, "completed": 0, "open": 0, "open_stale": 0})
    for i in issues:
        projects[str(i["project_id"])]["name"] = i["project__name"]
    for i in created:
        projects[str(i["project_id"])]["created"] += 1
    for i in completed:
        projects[str(i["project_id"])]["completed"] += 1
    for i in open_items:
        projects[str(i["project_id"])]["open"] += 1
        projects[str(i["project_id"])]["open_stale"] += int(is_stale(i))

    # ── interactions ─────────────────────────────────────────────────────────
    window_comments = [c for c in comments if in_window(c["created_at"])]
    reply_latency = []
    replies_by = defaultdict(list)
    pairs = defaultdict(list)
    last_by_issue = {}
    for c in comments:
        prev = last_by_issue.get(c["issue_id"])
        if prev and prev["actor_id"] != c["actor_id"] and in_window(c["created_at"]):
            latency = _hours(c["created_at"] - prev["created_at"])
            reply_latency.append(latency)
            replies_by[c["actor_id"]].append(latency)
            if c["actor_id"] in humans and prev["actor_id"] in humans:
                pairs[(prev["actor_id"], c["actor_id"])].append(latency)
        last_by_issue[c["issue_id"]] = c

    notifications = list(
        Notification.objects.filter(workspace_id=workspace.id, created_at__gte=start, created_at__lt=end).values(
            "receiver_id", "sender", "created_at", "read_at"
        )
    )
    human_notes = [n for n in notifications if n["receiver_id"] in humans]
    read_notes = [n for n in human_notes if n["read_at"]]
    emails = EmailNotificationLog.objects.filter(
        entity_identifier__in=issue_ids, sent_at__gte=start, sent_at__lt=end
    ).count()

    interactions = {
        "comments": len(window_comments),
        "commenters": len({c["actor_id"] for c in window_comments if c["actor_id"] in humans}),
        "issues_commented": len({c["issue_id"] for c in window_comments}),
        "reply_latency_hours": _stats(reply_latency),
        "mentions": sum(1 for n in human_notes if n["sender"].endswith(":mentioned")),
        "notifications": len(human_notes),
        "notifications_read_rate": _rate(len(read_notes), len(human_notes)),
        "time_to_read_hours": _stats(_hours(n["read_at"] - n["created_at"]) for n in read_notes),
        "emails": emails,
        # who answers whom in comment threads (A wrote, B answered)
        "reply_pairs": sorted(
            (
                {
                    "from": names.get(a, ""),
                    "to": names.get(b, ""),
                    "replies": len(lat),
                    "median_hours": _median(lat),
                }
                for (a, b), lat in pairs.items()
            ),
            key=lambda p: -p["replies"],
        )[:12],
    }

    # ── when the team works (Argentina time) ─────────────────────────────────
    heatmap = [[0] * 24 for _ in range(7)]
    action_days = defaultdict(set)
    activity_by_person = defaultdict(int)
    for when, actor in [(a["created_at"], a["actor_id"]) for a in activities] + [
        (c["created_at"], c["actor_id"]) for c in comments
    ]:
        if not in_window(when) or actor not in humans:
            continue
        local = when.astimezone(TZ)
        heatmap[local.weekday()][local.hour] += 1
        action_days[actor].add(local.date())
        activity_by_person[actor] += 1
    for p in Page.objects.filter(workspace_id=workspace.id, updated_at__gte=start, updated_at__lt=end).values(
        "updated_by_id", "updated_at"
    ):
        if p["updated_by_id"] in humans:
            activity_by_person[p["updated_by_id"]] += 1
            action_days[p["updated_by_id"]].add(p["updated_at"].astimezone(TZ).date())

    # ── usage (UsageDay counts start the day it was deployed) ────────────────
    usage_rows = list(
        UsageDay.objects.filter(workspace_slug=workspace.slug, date__gte=since, date__lt=until).values(
            "date", "user_id", "surface", "channel", "reads", "writes", "last_at"
        )
    )
    human_usage = [r for r in usage_rows if r["user_id"] in humans]
    daily = defaultdict(lambda: {"active": set(), "writers": set(), "requests": 0})
    surfaces = defaultdict(lambda: {"users": set(), "reads": 0, "writes": 0})
    for r in human_usage:
        d = daily[r["date"].isoformat()]
        d["active"].add(r["user_id"])
        d["requests"] += r["reads"] + r["writes"]
        if r["writes"]:
            d["writers"].add(r["user_id"])
        s = surfaces[r["surface"]]
        s["users"].add(r["user_id"])
        s["reads"] += r["reads"]
        s["writes"] += r["writes"]

    usage = {
        "members": len(humans),
        "bots": len(bots),
        "active_users": len({r["user_id"] for r in human_usage}),
        "writers": len([uid for uid, n in activity_by_person.items() if n]),
        "bot_actions": sum(1 for a in activities if in_window(a["created_at"]) and a["actor_id"] in bots)
        + sum(1 for c in window_comments if c["actor_id"] in bots),
        "api_requests": sum(r["reads"] + r["writes"] for r in usage_rows if r["channel"] == "api"),
        "daily": [
            {"date": day, "active_users": len(v["active"]), "writers": len(v["writers"]), "requests": v["requests"]}
            for day, v in sorted(daily.items())
        ],
        "surfaces": {
            name: {"users": len(v["users"]), "reads": v["reads"], "writes": v["writes"]}
            for name, v in sorted(surfaces.items())
        },
        "tracking_since": min((r["date"] for r in usage_rows), default=None),
        "heatmap": heatmap,
    }

    # ── per person ───────────────────────────────────────────────────────────
    people = []
    for uid, user in humans.items():
        mine = [r for r in human_usage if r["user_id"] == uid]
        assigned_open = [i for i in open_items if uid in assignees[i["id"]]]
        my_done = [i for i in completed if uid in assignees[i["id"]]]
        my_dated = [i for i in my_done if i["target_date"]]
        notes = [n for n in human_notes if n["receiver_id"] == uid]
        people.append(
            {
                "user_id": str(uid),
                "name": names[uid],
                "email": user.email,
                "active_days": len({r["date"] for r in mine}),
                "action_days": len(action_days.get(uid, ())),
                "requests": sum(r["reads"] + r["writes"] for r in mine),
                "actions": activity_by_person.get(uid, 0),
                "comments": sum(1 for c in window_comments if c["actor_id"] == uid),
                "created": sum(1 for i in created if i["created_by_id"] == uid),
                "completed_assigned": len(my_done),
                "lead_time_median_hours": _median(_hours(i["completed_at"] - i["created_at"]) for i in my_done),
                "start_after_assignment_median_hours": _median(
                    _hours(first_started[i["id"]] - assigned_at[(i["id"], uid)])
                    for i in my_done
                    if i["id"] in first_started and (i["id"], uid) in assigned_at
                ),
                "on_time_rate": _rate(sum(1 for i in my_dated if on_time(i)), len(my_dated)),
                "reply_median_hours": _median(replies_by.get(uid, [])),
                "open_assigned": len(assigned_open),
                "open_stale": sum(1 for i in assigned_open if is_stale(i)),
                "open_overdue": sum(1 for i in assigned_open if is_overdue(i)),
                "notifications": len(notes),
                "notifications_read": sum(1 for n in notes if n["read_at"]),
                "last_seen": max((r["last_at"] for r in mine), default=user.last_active),
            }
        )
    people.sort(key=lambda p: (-p["actions"], -p["completed_assigned"], p["name"]))

    # ── per client (modules are used as the client list) ─────────────────────
    clients = {}

    def client_row(issue):
        rows = []
        for name in modules_of.get(issue["id"], []):
            key = _client_key(name)
            if not key:
                continue
            row = clients.setdefault(
                key,
                {
                    "name": name,
                    "created": 0,
                    "completed": 0,
                    "open": 0,
                    "open_stale": 0,
                    "comments": 0,
                    "reopens": 0,
                    "_lead": [],
                },
            )
            rows.append(row)
        return rows

    for i in created:
        for row in client_row(i):
            row["created"] += 1
    for i in completed:
        for row in client_row(i):
            row["completed"] += 1
            row["_lead"].append(_hours(i["completed_at"] - i["created_at"]))
            row["reopens"] += reopens.get(i["id"], 0)
    for i in open_items:
        for row in client_row(i):
            row["open"] += 1
            row["open_stale"] += int(is_stale(i))
    for c in window_comments:
        for row in client_row(issue_by_id[c["issue_id"]]):
            row["comments"] += 1
    client_list = []
    for row in clients.values():
        lead = row.pop("_lead")
        row["lead_time_median_hours"] = _median(lead)
        if row["created"] or row["completed"] or row["open"]:
            client_list.append(row)
    client_list.sort(key=lambda r: -(r["completed"] + r["open"] + r["created"]))

    # ── items to act on ──────────────────────────────────────────────────────
    def item(i, days):
        url = f"{web_url}/{workspace.slug}/projects/{i['project_id']}/issues/{i['id']}" if web_url else ""
        return {
            "id": str(i["id"]),
            "key": f"{i['project__identifier']}-{i['sequence_id']}",
            "name": i["name"],
            "project": i["project__name"],
            "state": i["state__name"],
            "assignees": sorted(names.get(a, "") for a in assignees[i["id"]]),
            "client": (modules_of.get(i["id"]) or [""])[0],
            "days": days,
            "target_date": i["target_date"],
            "url": url,
        }

    stale_items = sorted(
        (item(i, (end - touched(i)).days) for i in open_items if is_stale(i)), key=lambda x: -x["days"]
    )[:LIST_LIMIT]
    overdue_items = sorted(
        (item(i, (end_date - i["target_date"]).days) for i in open_items if is_overdue(i)), key=lambda x: -x["days"]
    )[:LIST_LIMIT]
    unassigned_items = sorted(
        (item(i, (end - i["created_at"]).days) for i in open_items if not assignees[i["id"]]),
        key=lambda x: -x["days"],
    )[:LIST_LIMIT]

    return {
        "workspace_slug": workspace.slug,
        "since": since.isoformat(),
        "until": until.isoformat(),
        "usage": usage,
        "flow": flow,
        "interactions": interactions,
        "projects": sorted(projects.values(), key=lambda p: -(p["created"] + p["completed"] + p["open"])),
        "clients": client_list,
        "people": people,
        "items": {"stale": stale_items, "overdue": overdue_items, "unassigned": unassigned_items},
    }
