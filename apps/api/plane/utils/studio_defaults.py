# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
Opt-in "new client project" skeleton for the Zil design studio.

Layers a standard set of extra states and deliverable labels on top of the
project's regular ``DEFAULT_STATES`` (see plane.db.models.state) so a new
client project doesn't have to be rebuilt by hand every time. Only runs when
explicitly requested — see ``ProjectViewSet.create`` in
plane/app/views/project/base.py, gated behind the
``zil_seed_studio_defaults`` request flag.
"""

from plane.db.models import Label, State
from plane.utils.state_group_matcher import match_state_group

# Extra states layered on top of DEFAULT_STATES (Backlog/Todo/In
# Progress/Done/Cancelled/Triage). Groups are derived from the name via the
# same keyword matcher the Notion importer uses, so the mapping stays in
# sync with a single source of truth. Sequence values sort after every
# DEFAULT_STATES entry (max sequence 65000).
STUDIO_STATES = [
    {"name": "Briefing", "color": "#26B5CE", "sequence": 70000},
    {"name": "Propuesta inicial", "color": "#3F76FF", "sequence": 75000},
    {"name": "Correcciones", "color": "#FB923C", "sequence": 80000},
    {"name": "Entrega", "color": "#22C55E", "sequence": 85000},
    {"name": "Suspendidos", "color": "#EF4444", "sequence": 90000},
]

# Standard deliverable labels for a new client project.
STUDIO_LABELS = [
    {"name": "Branding", "color": "#F97316"},
    {"name": "Web", "color": "#3B82F6"},
    {"name": "Landing", "color": "#8B5CF6"},
    {"name": "Redes Sociales", "color": "#EC4899"},
    {"name": "Email", "color": "#10B981"},
    {"name": "Merchandising", "color": "#EAB308"},
]


def seed_studio_defaults(project, workspace, user):
    """Seed the studio's standard client-project skeleton onto ``project``:
    STUDIO_STATES (mapped to Plane state groups) and STUDIO_LABELS.

    Additive only — must be called right after a project (and its
    DEFAULT_STATES) is created, never against an existing project, since it
    does not check for pre-existing states/labels with the same name.
    """
    State.objects.bulk_create(
        [
            State(
                name=state["name"],
                color=state["color"],
                project=project,
                workspace=workspace,
                sequence=state["sequence"],
                group=match_state_group(state["name"]),
                created_by=user,
            )
            for state in STUDIO_STATES
        ]
    )

    Label.objects.bulk_create(
        [
            Label(
                name=label["name"],
                color=label["color"],
                project=project,
                workspace=workspace,
                created_by=user,
            )
            for label in STUDIO_LABELS
        ]
    )
