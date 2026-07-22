# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
Keyword-based mapping from a free-text status/state name (EN/ES) to a Plane
``StateGroup`` value.

Shared by the Notion importer (classifying imported Notion statuses) and the
Zil studio project-skeleton seeder (classifying the studio's standard extra
states), so both stay in sync with a single keyword table.
"""

import re

# keyword -> Plane state group (EN/ES). Checked in order; first substring
# hit wins, default "unstarted".
_STATE_GROUP_KEYWORDS = (
    ("cancelled", ("cancel", "cancelado", "cancelada", "cancelados", "canceladas", "cancelled", "suspendido", "suspendida", "suspendidos", "suspendidas", "pausado", "pausados", "descartado", "descartados", "abandonado", "abandonados")),
    ("completed", ("done", "complete", "completed", "completado", "completada", "completados", "completadas", "terminado", "terminada", "terminados", "finalizado", "finalizada", "finalizados", "hecho", "hechos", "entrega", "entregas", "entregado", "entregados", "delivered", "shipped", "cerrado", "cerrados")),
    ("started", ("progress", "progreso", "curso", "doing", "correccion", "corrección", "correcciones", "revision", "revisión", "revisiones", "review", "desarrollo", "haciendo")),
    ("backlog", ("backlog", "idea", "ideas")),
)
# multi-word phrases matched as substrings (word-token match can't see these)
_STATE_GROUP_PHRASES = (
    ("cancelled", ("on hold",)),
    ("started", ("en curso", "in progress")),
)


def match_state_group(name):
    lowered = name.strip().lower()
    for group, phrases in _STATE_GROUP_PHRASES:
        if any(phrase in lowered for phrase in phrases):
            return group
    tokens = set(re.split(r"[^0-9a-záéíóúñü]+", lowered))
    for group, keywords in _STATE_GROUP_KEYWORDS:
        if tokens.intersection(keywords):
            return group
    return "unstarted"
