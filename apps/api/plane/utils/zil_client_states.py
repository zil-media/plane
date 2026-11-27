# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""The same states in every client (brand) project of a workspace, copied from a model project.

A workspace admin picks a project (for example "Team Meraki") whose states every client should
use (`ZilClientStatesTemplate`). Applying it, client by client:

- every state of the model exists in the client, with the model's name, color, group and order
  (a state already named like it, ignoring case, is updated instead of duplicated);
- a work item in any other state moves to the model's state of the same group (lo pendiente a
  Pendiente, lo que está en curso a En proceso, lo terminado a Finalizado). A group the model
  lacks falls back to the closest open one for open work; finished or cancelled work with nowhere
  of its own kind to go stays in its state, which is then kept;
- the states left empty are removed; Triage (Intake) is never touched;
- the model's default state is the client's default.

No work item is ever lost or deleted, and re-applying changes nothing. The move is a direct update,
so nobody gets a notification per work item. A client that fails is reported and does not stop
the others. New client projects are born with the model's states (`template_states_for`).
"""

# Python imports
import logging

# Django imports
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone
from django.utils.text import slugify

# Module imports
from plane.db.models import (
    DraftIssue,
    Issue,
    Project,
    State,
    ZilBrandProject,
    ZilClientStatesTemplate,
)
from plane.db.models.state import StateGroup
from plane.utils.agent_pipeline.flags import is_feature_enabled

logger = logging.getLogger("plane.zil.client_states")

FLAG_KEY = "clientStatesTemplate"

BACKLOG = StateGroup.BACKLOG.value
UNSTARTED = StateGroup.UNSTARTED.value
STARTED = StateGroup.STARTED.value
COMPLETED = StateGroup.COMPLETED.value
CANCELLED = StateGroup.CANCELLED.value

# where a work item of each group goes when the model has no state of that group
GROUP_FALLBACKS = {
    BACKLOG: (BACKLOG, UNSTARTED, STARTED),
    UNSTARTED: (UNSTARTED, BACKLOG, STARTED),
    STARTED: (STARTED, UNSTARTED, BACKLOG),
    COMPLETED: (COMPLETED,),
    CANCELLED: (CANCELLED,),
}


def client_projects(workspace_id):
    """Every brand (client) project of the workspace, archived ones included."""
    return Project.objects.filter(
        workspace_id=workspace_id,
        zil_brand__kind=ZilBrandProject.BRAND_KIND,
        zil_brand__deleted_at__isnull=True,
    )


def get_template(workspace_id):
    return ZilClientStatesTemplate.objects.filter(workspace_id=workspace_id).select_related("template_project").first()


def template_states(template_project):
    """The model's states, in order (Triage left out)."""
    return list(State.objects.filter(project=template_project).order_by("sequence", "created_at"))


def template_states_for(workspace_id):
    """The states a new client project of this workspace is born with, or None for the usual ones."""
    if not is_feature_enabled(FLAG_KEY):
        return None
    template = get_template(workspace_id)
    project = template.template_project if template else None
    if project is None or project.archived_at is not None or project.deleted_at is not None:
        return None
    states = template_states(project)
    if not states:
        return None
    has_default = any(state.default for state in states)
    return [
        {
            "name": state.name,
            "color": state.color,
            "sequence": state.sequence,
            "group": state.group,
            "default": state.default if has_default else index == 0,
        }
        for index, state in enumerate(states)
    ]


def _target_for(group, kept_by_group):
    for candidate in GROUP_FALLBACKS.get(group, ()):
        if kept_by_group.get(candidate):
            return kept_by_group[candidate][0]
    return None


def _apply_to_project(project, model_states, user_id):
    """Give one client the model's states. Returns how many work items changed state."""
    existing = list(State.objects.filter(project=project).order_by("sequence", "created_at"))
    by_name = {}
    for state in existing:
        by_name.setdefault(state.name.strip().casefold(), state)
    claimed = set()

    kept = []
    for model_state in model_states:
        state = next((s for s in existing if s.name == model_state.name and s.pk not in claimed), None)
        if state is None:
            state = by_name.get(model_state.name.strip().casefold())
        if state is not None and state.pk in claimed:
            state = None
        if state is None:
            state = State(
                name=model_state.name,
                slug=slugify(model_state.name),
                color=model_state.color,
                sequence=model_state.sequence,
                group=model_state.group,
                project=project,
                workspace_id=project.workspace_id,
                created_by_id=user_id,
                updated_by_id=user_id,
            )
            # bulk_create: State.save() would overwrite the model's sequence
            State.objects.bulk_create([state])
        elif (state.name, state.color, state.sequence, state.group) != (
            model_state.name,
            model_state.color,
            model_state.sequence,
            model_state.group,
        ):
            State.objects.filter(pk=state.pk).update(
                name=model_state.name,
                slug=slugify(model_state.name),
                color=model_state.color,
                sequence=model_state.sequence,
                group=model_state.group,
                updated_by_id=user_id,
                updated_at=timezone.now(),
            )
        claimed.add(state.pk)
        kept.append((model_state, state))

    kept_by_group = {}
    for model_state, state in kept:
        kept_by_group.setdefault(model_state.group, []).append(state)

    moved = 0
    removed = []
    others = [state for state in existing if state.pk not in claimed]
    for state in others:
        target = _target_for(state.group, kept_by_group)
        if target is None:
            continue
        moved += Issue.all_objects.filter(state=state, deleted_at__isnull=True).count()
        Issue.all_objects.filter(state=state).update(state=target)
        DraftIssue.all_objects.filter(state=state).update(state=target)
        Project.objects.filter(pk=project.pk, default_state=state).update(default_state=target)
        removed.append(state.pk)
    # states that stay because the model has nothing of their kind (finished or cancelled work)
    leftovers = [state for state in others if state.pk not in removed]

    if removed:
        State.all_state_objects.filter(pk__in=removed).update(deleted_at=timezone.now())

    default_pk = next((state.pk for model_state, state in kept if model_state.default), None)
    if default_pk is None and kept:
        default_pk = kept[0][1].pk
    if default_pk is not None:
        State.objects.filter(project=project, default=True).exclude(pk=default_pk).update(default=False)
        State.objects.filter(pk=default_pk, default=False).update(default=True)
    if leftovers:
        logger.info("client %s keeps %d state(s) the model has no group for", project.id, len(leftovers))
    return moved


def preview(workspace_id, template_project):
    """How many clients and work items applying the model would touch, without changing anything."""
    model_groups = {state.group for state in template_states(template_project)}
    model_names = {state.name.strip().casefold() for state in template_states(template_project)}
    projects = client_projects(workspace_id).exclude(pk=template_project.pk)
    moving = 0
    for state in (
        State.objects.filter(project__in=projects)
        .annotate(items=Count("state_issue", filter=Q(state_issue__deleted_at__isnull=True)))
        .values("name", "group", "items")
    ):
        if state["name"].strip().casefold() in model_names:
            continue
        if any(group in model_groups for group in GROUP_FALLBACKS.get(state["group"], ())):
            moving += state["items"]
    return {"clients": projects.count(), "work_items_to_move": moving}


def apply_client_states(workspace_id, template_project, user_id=None):
    """Give every client project of the workspace the model's states.

    Returns {"clients": n, "updated": n, "work_items_moved": n, "failed": [project ids]}.
    """
    model_states = template_states(template_project)
    stats = {"clients": 0, "updated": 0, "work_items_moved": 0, "failed": []}
    if not model_states:
        return stats
    for project in client_projects(workspace_id).exclude(pk=template_project.pk).order_by("created_at"):
        stats["clients"] += 1
        try:
            with transaction.atomic():
                stats["work_items_moved"] += _apply_to_project(project, model_states, user_id)
            stats["updated"] += 1
        except Exception:
            logger.exception("could not apply client states to project %s", project.id)
            stats["failed"].append(str(project.id))
    return stats
