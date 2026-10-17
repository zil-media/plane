# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Usage, interaction and timing metrics of one workspace, and of one member, over a window of days.

Read by Zil Workspace (GET /api/zil/sync/metrics/ and /api/zil/sync/metrics/person/), which snapshots them
daily and shows them in Gestión Ops. Days are Argentina days; `until` is exclusive. People are the
workspace's human members; bots (AI agents, the Zil service user) are counted apart.

A member's row in the unit's people list and the totals/work of their own page come from one function
(`_person_fields`) over data loaded one way (`_Work`), so the two screens agree by definition:
- `actions`: changes to work items (without the activity twin Plane logs for each new comment), comments
  and page saves (one per editing session of a page, see `_page_saves`). `action_days`: days with an action.
- `active_*` (days, minutes, sessions): presence in Ops, which is an action, reading a notification, a
  request or a page autosave. A day with only reads counts in `active_days`, never in `action_days`.
- `created`: work items they created (intake requests still in triage are not work yet).
- `completed_assigned`: items assigned to them completed in the window, whoever closed them; the person page
  also shows `completed_marked`, the items this person moved to completed, whoever they were assigned to.

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
    PageVersion,
    State,
    UsageDay,
    WorkspaceMember,
)

TZ = ZoneInfo("America/Argentina/Buenos_Aires")
STALE_DAYS = 14
READY_MIN_DESCRIPTION = 50
DONE_GROUPS = {"completed", "cancelled"}
# intake requests (pending or declined) sit in the triage state: they are not work yet
NOT_OPEN_GROUPS = {"cancelled", "triage"}
LIST_LIMIT = 30
SEED_BOT_TYPE = "WORKSPACE_SEED"
SESSION_GAP = timedelta(minutes=30)
SESSION_MIN_MINUTES = 5
# closed this soon after being created: the work was logged once done, it never waited
LOGGED_DONE = timedelta(minutes=5)
TIMELINE_LIMIT = 60
AGE_BUCKETS = (("0-7 d", 0, 7), ("8-14 d", 8, 14), ("15-30 d", 15, 30), ("31-60 d", 31, 60), ("60+ d", 61, None))
ISSUE_FIELDS = (
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
ACTIVITY_FIELDS = (
    "issue_id",
    "field",
    "verb",
    "old_value",
    "new_value",
    "old_identifier",
    "new_identifier",
    "actor_id",
    "created_at",
)


def _hours(delta):
    return delta.total_seconds() / 3600


def _day(ts):
    return ts.astimezone(TZ).date()


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


def _lead_hours(issue):
    """Created → completed, or None for work logged after it was done: an item created already
    done (its completed_at is stamped a few ms before created_at) or closed within minutes of
    being created never waited. It counts as completed, but a 0 h "time to finish" would sink
    the median of a team that logs its work (Marketwise, Oct 2026: 0.2 h instead of 37 h)."""
    lead = issue["completed_at"] - issue["created_at"]
    return None if lead < LOGGED_DONE else _hours(lead)


def _on_time(issue):
    return issue["completed_at"].astimezone(TZ).date() <= issue["target_date"]


def _state_groups(workspace):
    """State id → group. State changes are resolved by the ids the activity stores, so renamed
    or deleted states keep their meaning in the history."""
    return dict(State.all_state_objects.filter(workspace_id=workspace.id).values_list("id", "group"))


def _is_open(issue, end):
    if issue["state__group"] in NOT_OPEN_GROUPS or (issue["archived_at"] and issue["completed_at"] is None):
        return False
    return issue["completed_at"] is None or issue["completed_at"] >= end


def _client_key(name):
    """Module names spelled differently across projects ("GEN-IT", "Gen It") are one client."""
    return re.sub(r"[^a-z0-9]", "", (name or "").casefold())


def _person_name(user):
    return user.display_name or f"{user.first_name} {user.last_name}".strip() or user.email


def _is_comment_twin(act):
    """Plane logs each new comment twice: the IssueComment and an IssueActivity "created" on field "comment".
    The comment is counted from IssueComment; editing or deleting a comment is an action of its own."""
    return act["field"] == "comment" and act["verb"] == "created"


def _kind(act, state_group):
    """What an IssueActivity row means for the person who did it."""
    field = act["field"]
    if field == "state":
        group = state_group.get(act["new_identifier"])
        return "completed" if group == "completed" else "started" if group == "started" else "state"
    if field is None and act["verb"] == "created":
        return "created"
    if field == "assignees":
        return "assigned"
    if field in ("cycles", "modules"):
        return "planned"
    if field in ("link", "attachment"):
        return "attached"
    return "edited"


class _Window:
    """since/until (Argentina days, `until` exclusive) as datetimes, and the cutoffs taken at its end."""

    def __init__(self, since, until):
        self.since, self.until = since, until
        self.start = datetime.combine(since, time.min, TZ)
        self.end = datetime.combine(until, time.min, TZ)
        self.end_date = until - timedelta(days=1)
        self.stale_cutoff = self.end - timedelta(days=STALE_DAYS)

    def has(self, ts):
        return ts is not None and self.start <= ts < self.end


def _page_saves(workspace, win, person_id=None):
    """Page edits in the window: (saves, moments). A save is one editing session of a page, (person, when it
    started, page name); every moment, (person, when), shows the person was there.

    Plane writes a version while someone edits, not when they decide to save: one person's saves of a page
    within 10 minutes of the version's start go into it, so a 2-hour session leaves 12 versions, and two people
    editing a page together leave one per autosave (~10 s), as each save goes to whoever typed last. One
    person's versions of a page less than 30 minutes apart are therefore one save; each version still counts
    as presence, for active time. A save belongs to the window its session started in. Versions Plane hid (it
    keeps the last 20 of a page) count until the nightly cleanup deletes them. A page edited in the window with
    no version of that person (a rename, a move, or pages saved before versions were recorded, Oct 2026)
    counts its last edit once."""
    # versions of the SESSION_GAP before the window say whether the first one inside it goes on with a session
    # that started the day before: that save was counted by the window it started in, so adjacent windows add up
    versions = PageVersion.all_objects.filter(
        workspace_id=workspace.id,
        page__deleted_at__isnull=True,
        last_saved_at__gte=win.start - SESSION_GAP,
        last_saved_at__lt=win.end,
    )
    pages = Page.objects.filter(workspace_id=workspace.id, updated_at__gte=win.start, updated_at__lt=win.end)
    if person_id is not None:
        versions = versions.filter(owned_by_id=person_id)
        pages = pages.filter(updated_by_id=person_id)
    edits = [
        (v["owned_by_id"], v["last_saved_at"], v["page_id"], v["page__name"] or "")
        for v in versions.values("page_id", "page__name", "owned_by_id", "last_saved_at")
    ]
    versioned = {(page_id, who) for who, ts, page_id, _ in edits if win.has(ts)}
    edits += [
        (p["updated_by_id"], p["updated_at"], p["id"], p["name"] or "")
        for p in pages.values("id", "name", "updated_by_id", "updated_at")
        if p["updated_by_id"] and (p["id"], p["updated_by_id"]) not in versioned
    ]
    saves, last = [], {}
    for who, ts, page_id, name in sorted(edits, key=lambda e: e[1]):
        prev = last.get((who, page_id))
        if win.has(ts) and (prev is None or ts - prev > SESSION_GAP):
            saves.append((who, ts, name))
        last[(who, page_id)] = ts
    return saves, [(who, ts) for who, ts, _, _ in edits if win.has(ts)]


class _Work:
    """What the unit view and the person view read, loaded one way. For one person (`person_id`) the queries
    are narrowed to what that person did, received or is assigned; every number `_person_fields` takes from
    it is the same as with the whole workspace loaded."""

    def __init__(self, workspace, win, person_id=None):
        self.win = win
        self.state_group = _state_groups(workspace)
        self.issues = {
            i["id"]: i
            for i in Issue.objects.filter(workspace_id=workspace.id, is_draft=False, created_at__lt=win.end)
            # Plane's onboarding demo items ("Welcome to Plane") are not work
            .exclude(created_by__bot_type=SEED_BOT_TYPE)
            .values(*ISSUE_FIELDS)
        }
        ids = list(self.issues)

        self.assignees = defaultdict(set)
        self.assigned_at = {}
        self.first_assigned = {}
        assignments = IssueAssignee.objects.filter(issue_id__in=ids)
        if person_id is not None:
            assignments = assignments.filter(assignee_id=person_id)
        for a in assignments.values("issue_id", "assignee_id", "created_at").order_by("created_at"):
            self.assignees[a["issue_id"]].add(a["assignee_id"])
            self.assigned_at[(a["issue_id"], a["assignee_id"])] = a["created_at"]
            self.first_assigned.setdefault(a["issue_id"], a["created_at"])

        # whole history of the items (the person view only needs the items assigned to them)
        history_ids = ids if person_id is None else [i for i in ids if self.assignees.get(i)]
        self.history = list(
            IssueActivity.objects.filter(issue_id__in=history_ids, created_at__lt=win.end)
            .values(*ACTIVITY_FIELDS)
            .order_by("created_at", "id")
        )
        acted = (
            self.history
            if person_id is None
            else list(
                IssueActivity.objects.filter(
                    issue_id__in=ids, actor_id=person_id, created_at__gte=win.start, created_at__lt=win.end
                )
                .values(*ACTIVITY_FIELDS)
                .order_by("created_at", "id")
            )
        )
        self.comments = list(
            IssueComment.objects.filter(issue_id__in=ids, created_at__lt=win.end)
            .values("issue_id", "actor_id", "created_at")
            .order_by("created_at", "id")
        )

        # last time anyone touched an item (any change or comment) and when it was first started
        self.last_touch, self.first_started = {}, {}
        for act in self.history:
            iid = act["issue_id"]
            self.last_touch[iid] = act["created_at"]
            if (
                act["field"] == "state"
                and iid not in self.first_started
                and self.state_group.get(act["new_identifier"]) == "started"
            ):
                self.first_started[iid] = act["created_at"]
        for c in self.comments:
            self.last_touch[c["issue_id"]] = max(self.last_touch.get(c["issue_id"], c["created_at"]), c["created_at"])

        issues = self.issues.values()
        self.created = [i for i in issues if win.has(i["created_at"]) and i["state__group"] != "triage"]
        self.completed = [i for i in issues if win.has(i["completed_at"]) and i["state__group"] == "completed"]
        self.open_items = [i for i in issues if _is_open(i, win.end)]

        # every action in the window, oldest first: (when, who, kind, item | None, detail)
        actions = [
            (
                act["created_at"],
                act["actor_id"],
                _kind(act, self.state_group),
                self.issues[act["issue_id"]],
                act["new_value"] if act["field"] == "state" else (act["field"] or ""),
            )
            for act in acted
            if win.has(act["created_at"]) and not _is_comment_twin(act)
        ]
        actions += [
            (c["created_at"], c["actor_id"], "comment", self.issues[c["issue_id"]], "")
            for c in self.comments
            if win.has(c["created_at"])
        ]
        page_saves, self.page_moments = _page_saves(workspace, win, person_id)
        actions += [(ts, uid, "page", None, name) for uid, ts, name in page_saves]
        actions.sort(key=lambda e: e[0])
        self.actions = actions

        # replies in comment threads: (who wrote, who answered, hours to answer), answered in the window
        self.replies = []
        last_by_issue = {}
        for c in self.comments:
            prev = last_by_issue.get(c["issue_id"])
            if prev and prev["actor_id"] != c["actor_id"] and win.has(c["created_at"]):
                self.replies.append((prev["actor_id"], c["actor_id"], _hours(c["created_at"] - prev["created_at"])))
            last_by_issue[c["issue_id"]] = c

        notes = Notification.objects.filter(
            workspace_id=workspace.id, created_at__gte=win.start, created_at__lt=win.end
        )
        usage = UsageDay.objects.filter(workspace_slug=workspace.slug, date__gte=win.since, date__lt=win.until)
        if person_id is not None:
            notes = notes.filter(receiver_id=person_id)
            usage = usage.filter(user_id=person_id)
        self.notes = list(notes.values("receiver_id", "sender", "created_at", "read_at"))
        self.usage = list(usage.values("date", "user_id", "surface", "channel", "reads", "writes", "last_at"))

    def touched(self, issue):
        return max(self.last_touch.get(issue["id"], issue["created_at"]), issue["created_at"])

    def is_stale(self, issue):
        return self.touched(issue) < self.win.stale_cutoff

    def is_overdue(self, issue):
        return bool(issue["target_date"]) and issue["target_date"] < self.win.end_date


def _presence(work, uid):
    """Signs of presence that are not actions: (reads, other moments). Reading a notification ("mark all as
    read" stamps hundreds within the same second: one moment, not hundreds); the last request of each
    (surface, channel) of a day; every autosave of a page they edited."""
    win = work.win
    reads = sorted(
        {
            n["read_at"].replace(second=0, microsecond=0)
            for n in work.notes
            if n["receiver_id"] == uid and win.has(n["read_at"])
        }
    )
    pings = [r["last_at"] for r in work.usage if r["user_id"] == uid and win.has(r["last_at"])]
    return reads, pings + [ts for who, ts in work.page_moments if who == uid]


def _person_fields(work, user):
    """One member's numbers, as both the unit's people list and the member's own page show them."""
    uid = user.id
    actions = [e for e in work.actions if e[1] == uid]
    notes = [n for n in work.notes if n["receiver_id"] == uid]
    read_notes = [n for n in notes if n["read_at"]]
    usage = [r for r in work.usage if r["user_id"] == uid]
    reads, pings = _presence(work, uid)
    action_days = {_day(e[0]) for e in actions}
    done = [i for i in work.completed if uid in work.assignees[i["id"]]]
    dated = [i for i in done if i["target_date"]]
    owed = [i for i in work.open_items if uid in work.assignees[i["id"]]]
    replies = [hours for _, actor, hours in work.replies if actor == uid]
    return {
        "actions": len(actions),
        "action_days": len(action_days),
        "active_days": len(action_days | {_day(ts) for ts in reads + pings}),
        "requests": sum(r["reads"] + r["writes"] for r in usage),
        "comments": sum(1 for e in actions if e[2] == "comment"),
        "created": sum(1 for i in work.created if i["created_by_id"] == uid),
        "completed_assigned": len(done),
        "lead_time_median_hours": _median(_lead_hours(i) for i in done),
        "start_after_assignment_median_hours": _median(
            _hours(work.first_started[i["id"]] - work.assigned_at[(i["id"], uid)])
            for i in done
            if i["id"] in work.first_started and (i["id"], uid) in work.assigned_at
        ),
        "on_time_rate": _rate(sum(1 for i in dated if _on_time(i)), len(dated)),
        "reply_median_hours": _median(replies),
        "replies": len(replies),
        "open_assigned": len(owed),
        "open_stale": sum(1 for i in owed if work.is_stale(i)),
        "open_overdue": sum(1 for i in owed if work.is_overdue(i)),
        "notifications": len(notes),
        "notifications_read": len(read_notes),
        "time_to_read_median_hours": _median(_hours(n["read_at"] - n["created_at"]) for n in read_notes),
        "last_seen": max((r["last_at"] for r in usage if r["last_at"]), default=user.last_active),
    }


def compute_workspace_metrics(workspace, since, until):
    win = _Window(since, until)
    start, end, end_date = win.start, win.end, win.end_date
    in_window = win.has
    web_url = (os.environ.get("WEB_URL") or "").rstrip("/")

    # ── people ───────────────────────────────────────────────────────────────
    members = {
        m.member_id: m.member
        for m in WorkspaceMember.objects.filter(workspace_id=workspace.id, is_active=True).select_related("member")
    }
    humans = {uid: u for uid, u in members.items() if not u.is_bot}
    bots = {uid for uid, u in members.items() if u.is_bot}
    names = {uid: _person_name(u) for uid, u in members.items()}

    # ── work items ───────────────────────────────────────────────────────────
    work = _Work(workspace, win)
    issues = list(work.issues.values())
    issue_ids = list(work.issues)
    issue_by_id = work.issues
    state_group = work.state_group
    assignees, first_assigned, first_started = work.assignees, work.first_assigned, work.first_started
    created, completed, open_items = work.created, work.completed, work.open_items
    touched, is_stale, is_overdue = work.touched, work.is_stale, work.is_overdue

    modules_of = defaultdict(list)
    for mi in ModuleIssue.objects.filter(issue_id__in=issue_ids).values("issue_id", "module__name"):
        if mi["module__name"]:
            modules_of[mi["issue_id"]].append(mi["module__name"])

    reopens = Counter()
    state_durations = defaultdict(list)
    last_state_change = {}
    for act in work.history:
        if act["field"] != "state":
            continue
        iid = act["issue_id"]
        new_group = state_group.get(act["new_identifier"])
        old_group = state_group.get(act["old_identifier"])
        if in_window(act["created_at"]):
            if old_group == "completed" and new_group not in DONE_GROUPS:
                reopens[iid] += 1
            # time spent in the state that is being left
            entered = last_state_change.get(iid, issue_by_id[iid]["created_at"])
            if act["old_value"]:
                state_durations[(act["old_value"], old_group or "")].append(_hours(act["created_at"] - entered))
        last_state_change[iid] = act["created_at"]

    comments = work.comments
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
        "lead_time_hours": _stats(_lead_hours(i) for i in completed),
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
        "on_time_rate": _rate(sum(1 for i in dated_done if _on_time(i)), len(dated_done)),
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
    pairs = defaultdict(list)
    for asker, replier, latency in work.replies:
        if replier in humans and asker in humans:
            pairs[(asker, replier)].append(latency)

    human_notes = [n for n in work.notes if n["receiver_id"] in humans]
    read_notes = [n for n in human_notes if n["read_at"]]
    emails = EmailNotificationLog.objects.filter(
        entity_identifier__in=issue_ids, sent_at__gte=start, sent_at__lt=end
    ).count()

    interactions = {
        "comments": len(window_comments),
        "commenters": len({c["actor_id"] for c in window_comments if c["actor_id"] in humans}),
        "issues_commented": len({c["issue_id"] for c in window_comments}),
        "reply_latency_hours": _stats(latency for _, _, latency in work.replies),
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

    # ── when the team works (Argentina time): actions only, no reads ─────────
    heatmap = [[0] * 24 for _ in range(7)]
    for ts, actor, _, _, _ in work.actions:
        if actor in humans:
            local = ts.astimezone(TZ)
            heatmap[local.weekday()][local.hour] += 1

    # ── per person: the same numbers the person's own page shows ────────────
    people = [
        {"user_id": str(uid), "name": names[uid], "email": user.email, **_person_fields(work, user)}
        for uid, user in humans.items()
    ]
    people.sort(key=lambda p: (-p["actions"], -p["completed_assigned"], p["name"]))

    # ── usage (UsageDay counts start the day it was deployed) ────────────────
    usage_rows = work.usage
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
        "writers": sum(1 for p in people if p["actions"]),
        "bot_actions": sum(1 for e in work.actions if e[1] in bots),
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
            row["_lead"].append(_lead_hours(i))
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


# ── one person ─────────────────────────────────────────────────────────────────

EDIT_FIELDS = {"name", "description", "priority", "target_date", "start_date", "labels", "estimate_point", "parent"}


def _clock(hour):
    """Decimal hour (9.5) as "09:30"."""
    if hour is None:
        return None
    minutes = int(round(hour * 60))
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _decimal_hour(ts):
    return ts.hour + ts.minute / 60


def compute_person_metrics(workspace, user, since, until):
    """What one member did in Ops over a window: when (hour by hour), how much (estimated active
    time from the gaps between their actions), what kind of work and where, and what they owe.
    `totals` and `work` are the member's row of the unit's people list (`_person_fields`).

    Active time: every timestamped thing the person did (changes, comments, every page autosave, reading a
    notification, the last request of each day) is put on a line; actions less than 30 minutes
    apart are one session, and each session counts its span plus 5 minutes. The heatmap counts
    actions and notification reads.
    """
    win = _Window(since, until)
    end = win.end
    web_url = (os.environ.get("WEB_URL") or "").rstrip("/")
    uid = user.id

    names = {
        m.member_id: _person_name(m.member)
        for m in WorkspaceMember.objects.filter(workspace_id=workspace.id).select_related("member")
    }
    work = _Work(workspace, win, person_id=uid)
    fields = _person_fields(work, user)
    modules_of = defaultdict(list)
    for mi in ModuleIssue.objects.filter(issue_id__in=list(work.issues)).values("issue_id", "module__name"):
        if mi["module__name"]:
            modules_of[mi["issue_id"]].append(mi["module__name"])

    def key_of(i):
        return f"{i['project__identifier']}-{i['sequence_id']}"

    def url_of(i):
        return f"{web_url}/{workspace.slug}/projects/{i['project_id']}/issues/{i['id']}" if web_url else ""

    # ── what they did, one event per action ─────────────────────────────────
    events = [(ts, kind, issue, detail) for ts, actor, kind, issue, detail in work.actions if actor == uid]
    reads, pings = _presence(work, uid)

    # ── when ─────────────────────────────────────────────────────────────────
    heatmap = [[0] * 24 for _ in range(7)]
    heatmap_completed = [[0] * 24 for _ in range(7)]
    for ts, kind, _, _ in events:
        local = ts.astimezone(TZ)
        heatmap[local.weekday()][local.hour] += 1
        if kind == "completed":
            heatmap_completed[local.weekday()][local.hour] += 1
    for ts in reads:
        local = ts.astimezone(TZ)
        heatmap[local.weekday()][local.hour] += 1

    by_day = defaultdict(list)
    for ts in [e[0] for e in events] + reads + pings:
        by_day[_day(ts)].append(ts.astimezone(TZ))

    days = []
    day = since
    while day < until:
        moments = sorted(by_day.get(day, []))
        sessions, minutes = 0, 0.0
        if moments:
            first = prev = moments[0]
            for ts in moments[1:] + [None]:
                if ts is None or ts - prev > SESSION_GAP:
                    sessions += 1
                    minutes += (prev - first).total_seconds() / 60 + SESSION_MIN_MINUTES
                    first = ts
                prev = ts or prev
        day_events = [e for e in events if _day(e[0]) == day]
        days.append(
            {
                "date": day.isoformat(),
                "actions": len(day_events),
                "completed": sum(1 for e in day_events if e[1] == "completed"),
                "comments": sum(1 for e in day_events if e[1] == "comment"),
                "active_minutes": round(minutes),
                "sessions": sessions,
                "first": _clock(_decimal_hour(moments[0])) if moments else None,
                "last": _clock(_decimal_hour(moments[-1])) if moments else None,
                "first_hour": round(_decimal_hour(moments[0]), 2) if moments else None,
                "last_hour": round(_decimal_hour(moments[-1]), 2) if moments else None,
            }
        )
        day += timedelta(days=1)
    worked = [d for d in days if d["first_hour"] is not None]
    completions = [e[0].astimezone(TZ) for e in events if e[1] == "completed"]

    # ── what kind of work, and where ────────────────────────────────────────
    kinds = Counter(e[1] for e in events)
    projects = defaultdict(lambda: {"name": "", "actions": 0, "completed": 0})
    clients = {}
    for _, kind, issue, _ in events:
        if issue is None:
            continue
        row = projects[str(issue["project_id"])]
        row["name"] = issue["project__name"]
        row["actions"] += 1
        row["completed"] += int(kind == "completed")
        for name in modules_of.get(issue["id"], []):
            key = _client_key(name)
            if key:
                c = clients.setdefault(key, {"name": name, "actions": 0, "completed": 0})
                c["actions"] += 1
                c["completed"] += int(kind == "completed")

    # ── what they owe ────────────────────────────────────────────────────────
    owed = []
    for i in work.open_items:
        if uid not in work.assignees[i["id"]]:
            continue
        overdue = work.is_overdue(i)
        owed.append(
            {
                "id": str(i["id"]),
                "key": key_of(i),
                "name": i["name"],
                "project": i["project__name"],
                "state": i["state__name"],
                "client": (modules_of.get(i["id"]) or [""])[0],
                "target_date": i["target_date"],
                "idle_days": (end - work.touched(i)).days,
                "stale": work.is_stale(i),
                "overdue_days": (win.end_date - i["target_date"]).days if overdue else 0,
                "url": url_of(i),
            }
        )
    owed.sort(key=lambda x: (-x["overdue_days"], -x["idle_days"]))

    timeline = [
        {
            "at": ts.astimezone(TZ).isoformat(timespec="minutes"),
            "kind": kind,
            "key": key_of(issue) if issue else "",
            "name": issue["name"] if issue else detail,
            "detail": detail if issue else "",
            "url": url_of(issue) if issue else "",
        }
        for ts, kind, issue, detail in reversed(events[-TIMELINE_LIMIT:])
    ]

    return {
        "workspace_slug": workspace.slug,
        "since": since.isoformat(),
        "until": until.isoformat(),
        "person": {
            "user_id": str(uid),
            "name": names.get(uid) or _person_name(user),
            "email": user.email,
            "last_seen": fields["last_seen"],
        },
        "totals": {
            "actions": fields["actions"],
            "action_days": fields["action_days"],
            "active_days": fields["active_days"],
            "active_minutes": sum(d["active_minutes"] for d in days),
            "active_minutes_per_day": _median(d["active_minutes"] for d in worked),
            "sessions": sum(d["sessions"] for d in days),
            "comments": fields["comments"],
            "created": fields["created"],
            "completed_marked": kinds["completed"],
            "page_saves": kinds["page"],
            "requests": fields["requests"],
        },
        "rhythm": {
            "first_hour_median": _median(d["first_hour"] for d in worked),
            "last_hour_median": _median(d["last_hour"] for d in worked),
            "span_hours_median": _median(d["last_hour"] - d["first_hour"] for d in worked),
            "completion_hour_median": _median(_decimal_hour(ts) for ts in completions),
            "weekend_share": _rate(sum(1 for e in events if e[0].astimezone(TZ).weekday() >= 5), len(events)),
            "after_hours_share": _rate(sum(1 for e in events if not 8 <= e[0].astimezone(TZ).hour < 20), len(events)),
        },
        "work": {
            key: fields[key]
            for key in (
                "completed_assigned",
                "lead_time_median_hours",
                "start_after_assignment_median_hours",
                "on_time_rate",
                "reply_median_hours",
                "replies",
                "open_assigned",
                "open_stale",
                "open_overdue",
                "notifications",
                "notifications_read",
                "time_to_read_median_hours",
            )
        },
        "heatmap": heatmap,
        "heatmap_completed": heatmap_completed,
        "daily": days,
        "kinds": dict(kinds),
        "projects": sorted(projects.values(), key=lambda p: -p["actions"]),
        "clients": sorted(clients.values(), key=lambda c: -c["actions"]),
        "timeline": timeline,
        "owed": owed[:LIST_LIMIT],
    }
