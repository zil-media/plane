# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
Standard sub-issue checklists for Zil deliverable-type labels.

When a work item is tagged with one of the label names below, the checklist
auto-spawn task (``plane.bgtasks.zil_deliverable_checklist_task``) creates
the listed titles as sub-issues (children), skipping any title that already
exists under the same parent so re-runs never duplicate work.

This module is intentionally dependency-free (stdlib only) so the mapping
and dedupe logic can be unit tested without Django/Celery installed — see
``plane.tests.unit.bgtasks.test_zil_deliverable_checklist_task``.

Edit ``DELIVERABLE_CHECKLISTS`` below to change what gets created for a
deliverable type, or to add a new deliverable-type label — it is the single
source of truth.
"""

DELIVERABLE_CHECKLISTS = {
    "Branding": [
        "Brief y moodboard",
        "Concepto de marca",
        "Paleta de colores y tipografía",
        "Logo — propuestas",
        "Manual de marca",
    ],
    "Web": [
        "Wireframes",
        "Diseño UI",
        "Desarrollo frontend",
        "QA y pruebas",
        "Publicación / deploy",
    ],
    "Landing": [
        "Copy de landing",
        "Diseño de landing",
        "Maquetación",
        "QA y pruebas",
        "Publicación / deploy",
    ],
    "Redes Sociales": [
        "Calendario de contenido",
        "Diseño de piezas",
        "Copy y redacción",
        "Programación de publicaciones",
    ],
    "Email": [
        "Copy del email",
        "Diseño del email",
        "Maquetación HTML",
        "Pruebas de envío",
        "Envío / programación",
    ],
    "Merchandising": [
        "Selección de productos",
        "Diseño de artes",
        "Cotización con proveedor",
        "Aprobación de muestra",
        "Producción",
    ],
}

# Quick membership check for callers deciding whether a label list is worth
# dispatching the checklist task for at all.
DELIVERABLE_LABEL_NAMES = frozenset(DELIVERABLE_CHECKLISTS.keys())


def titles_for_labels(label_names, existing_titles=()):
    """Return the checklist titles that still need to be created.

    Combines every deliverable-type label's checklist (labels that aren't a
    known deliverable type contribute nothing), de-duplicating titles
    case-insensitively both against each other and against
    ``existing_titles`` (the names of sibling sub-issues that already
    exist), so the result only contains titles that are still missing.
    """
    seen = {title.strip().lower() for title in existing_titles}
    result = []
    for label_name in label_names:
        for title in DELIVERABLE_CHECKLISTS.get(label_name, []):
            key = title.strip().lower()
            if key in seen:
                continue
            seen.add(key)
            result.append(title)
    return result
