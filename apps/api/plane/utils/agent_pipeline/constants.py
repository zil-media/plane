# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from datetime import timedelta

# Readable-card categories. Mirrored in the web app (support constants) and in
# the agent instructions (docs/agents/*): change all three together.
REQUEST_CATEGORIES = (
    "Work items",
    "Proyectos",
    "Ciclos",
    "Módulos",
    "Páginas",
    "Vistas",
    "Intake",
    "Notificaciones",
    "Importaciones",
    "Configuración",
    "Sistema",
    "Otro",
)

BUG_PROGRESS_PHASES = ("investigando", "implementando", "probando", "dudas")
FEATURE_PROGRESS_PHASES = ("investigando", "implementando", "probando", "terminando", "dudas")

DISPLAY_TITLE_MAX = 70
PLAIN_SUMMARY_MAX = 200
PROGRESS_NOTE_MAX = 500

# An agent session that claimed a bug and went silent this long is presumed dead.
CLAIM_EXPIRY = timedelta(minutes=30)
# Shared across all API/worker processes through Redis.
BUG_ROUTINE_COOLDOWN = timedelta(minutes=10)
# Auto reports re-escalate to the agent every Nth occurrence, at most this often.
ESCALATE_EVERY = 10
ESCALATE_MIN_GAP = timedelta(minutes=15)
# A spec or build with no sign of life for this long goes back to its queue.
FEATURE_RUN_EXPIRY = timedelta(minutes=60)
MAX_SPEC_RUNS = 3

REOPEN_MIN_GAP = timedelta(minutes=5)

NOISE_PATTERNS = (
    "resizeobserver loop",
    "hot-update",
    "[hmr]",
    "strict mode",
    "script error.",
)
