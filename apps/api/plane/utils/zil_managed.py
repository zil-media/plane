# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""What Ops refuses on the projects Zil manages (one per brand, plus "Migración").

Zil Workspace alone decides who works on a brand, and a brand's project is always private: in Ops
nobody adds or removes its people (Zil agents excepted: they join a brand when someone adds them),
nobody makes it public, nobody changes its identifier (it is in every work item key), nobody
archives or restores it (Zil does, following the brand) and nobody deletes it (the brand is archived
in Workspace instead; "Migración" holds pages still to sort). Renaming it, and every other setting, stays
open. The answer is 409 with `code: ZIL_MANAGED`, which the web app shows as such.
"""

# Python imports
import re

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.db.models import BotTypeEnum, Project, User, ZilBrandProject

ZIL_MANAGED_CODE = "ZIL_MANAGED"

# Characters a Zil project name may not carry. Plane forbids many more in project names
# (`Project.FORBIDDEN_IDENTIFIER_CHARS_PATTERN`), which brand names do use ("Wendy's",
# "Dean & Dennys", "O2 - SportClub"); only what could pass for markup stays out.
ZIL_PROJECT_NAME_FORBIDDEN = re.compile(r"[<>{}]")


def zil_managed_conflict(what="This project"):
    return Response(
        {"error": f"{what} is managed by Zil Workspace", "code": ZIL_MANAGED_CODE},
        status=status.HTTP_409_CONFLICT,
    )


def zil_project_kind(project_id):
    return ZilBrandProject.objects.filter(project_id=project_id).values_list("kind", flat=True).first()


def project_name_is_forbidden(name, project=None):
    """Plane's rule for project names, relaxed for Zil's projects ("Wendy's", "Dean & Dennys")."""
    if project is not None and project.pk and zil_project_kind(project.pk):
        return bool(ZIL_PROJECT_NAME_FORBIDDEN.search(name))
    return bool(re.match(Project.FORBIDDEN_IDENTIFIER_CHARS_PATTERN, name))


def project_update_conflict(project, data):
    """409 when an update would make a Zil project public or change its identifier, else None."""
    if not zil_project_kind(project.pk):
        return None
    if "network" in data and str(data.get("network")) != str(project.network):
        return zil_managed_conflict("The visibility of this project")
    if "identifier" in data and str(data.get("identifier") or "").strip().upper() != project.identifier:
        return zil_managed_conflict("The identifier of this project")
    return None


def project_delete_conflict(project_id):
    """409 for every Zil project: a brand's is archived from Workspace, and "Migración" holds the
    pages of clients with several brands until they are sorted by hand (deleting it loses them)."""
    if zil_project_kind(project_id):
        return zil_managed_conflict()
    return None


def project_archive_conflict(project_id):
    """409 when someone archives or restores a Zil project by hand: Zil archives a brand's project
    when the brand leaves the workspace and restores it when it comes back, and a hand archive would
    hide a live brand from its team (or one restore bring back a dead one) until the next roster."""
    if zil_project_kind(project_id):
        return zil_managed_conflict("Archiving this project")
    return None


def is_zil_project(project_id):
    return ZilBrandProject.objects.filter(project_id=project_id).exists()


def project_membership_locked(project_id, member_ids=None):
    """Whether a membership change on `project_id` must be refused: a Zil project, and (when the
    change is about specific users) at least one of them a person rather than a Zil agent."""
    if not is_zil_project(project_id):
        return False
    if member_ids is None:
        return True
    agents = {
        str(pk)
        for pk in User.objects.filter(pk__in=member_ids, is_bot=True, bot_type=BotTypeEnum.ZIL_AGENT).values_list(
            "pk", flat=True
        )
    }
    return any(str(member_id) not in agents for member_id in member_ids)


def membership_conflict(project_id, member_ids=None):
    """409 when a membership change touches a person on a Zil project (agents are allowed)."""
    if project_membership_locked(project_id, member_ids):
        return zil_managed_conflict("The membership of this project")
    return None
