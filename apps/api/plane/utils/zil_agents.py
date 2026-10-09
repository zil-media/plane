# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Zil AI agents (ZIL_AGENT bots) as mentionable/assignable project members.

Bots are hidden from member pickers (`member__is_bot=False`); agents are the
exception, and they belong to every project of the workspaces Zil grants them
so people can assign them work.
"""

# Django imports
from django.db.models import Q

# Module imports
from plane.db.models import BotTypeEnum, Project, ProjectMember, WorkspaceMember

AGENT_MAX_PROJECT_ROLE = 15  # Member — an agent is never a project admin


def human_or_agent_member_q(prefix="member__"):
    """Member filter that keeps humans and Zil agents but no other bots."""
    return Q(**{f"{prefix}is_bot": False}) | Q(**{f"{prefix}bot_type": BotTypeEnum.ZIL_AGENT})


def _ensure_project_member(project_id, agent_id, role):
    membership = ProjectMember.objects.filter(project_id=project_id, member_id=agent_id).first()
    if membership is None:
        ProjectMember.objects.create(project_id=project_id, member_id=agent_id, role=role)
    elif not membership.is_active:
        membership.is_active = True
        membership.save(update_fields=["is_active"])


def sync_zil_agent_project_memberships(agent):
    """Make `agent` a member of every project of its active workspaces; drop the rest."""
    workspace_roles = dict(
        WorkspaceMember.objects.filter(member=agent, is_active=True).values_list("workspace_id", "role")
    )
    ProjectMember.objects.filter(member=agent, is_active=True).exclude(workspace_id__in=workspace_roles).update(
        is_active=False
    )
    if not agent.is_active:
        return
    for project_id, workspace_id in Project.objects.filter(workspace_id__in=workspace_roles).values_list(
        "id", "workspace_id"
    ):
        _ensure_project_member(project_id, agent.id, min(workspace_roles[workspace_id], AGENT_MAX_PROJECT_ROLE))


def add_zil_agents_to_project(project):
    """Add the workspace's active Zil agents to a newly created project."""
    agents = WorkspaceMember.objects.filter(
        workspace_id=project.workspace_id,
        is_active=True,
        member__is_bot=True,
        member__bot_type=BotTypeEnum.ZIL_AGENT,
        member__is_active=True,
    ).values_list("member_id", "role")
    for agent_id, role in agents:
        _ensure_project_member(project.id, agent_id, min(role, AGENT_MAX_PROJECT_ROLE))
