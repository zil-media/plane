# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""The one way the bug fixer repairs data a bug already left wrong.

A code fix only changes what happens next: the pages a bug made public stay public. The bug lane
may ship a data-only migration (check-agent-diff.mjs checks its shape) whose operation is
`RunPython(data_repair("<name>", repair), RunPython.noop)`.

The API container runs `migrate` on start and does not come up if a migration fails, so a repair
must never be able to take production down: it runs in a savepoint, and if it raises, only the
repair is undone, the deploy goes on, and the failure becomes a pipeline incident the bug fixer
picks up on its own (with the error, so it can ship a corrected repair).

Lives under agent_pipeline/ on purpose: the agent cannot edit it (denylisted).
"""

# Python imports
import logging
import traceback

# Django imports
from django.db import transaction

logger = logging.getLogger("plane.worker")


def data_repair(name, repair):
    """Wraps `repair(apps) -> rows changed` for RunPython."""

    def forward(apps, schema_editor):
        try:
            with transaction.atomic():
                changed = repair(apps)
        except Exception as e:
            logger.exception("data repair %s failed; undone, the deploy goes on", name)
            _report_failure(name, e)
            return
        logger.info("data repair %s: %s row(s) changed", name, changed)

    return forward


def _report_failure(name, error):
    # Its own savepoint: at this point of a fresh migrate the bug table may not match today's model,
    # and a failed report must not break the migration either.
    try:
        from plane.db.models import BugReport

        from .bugs import file_auto_bug_report

        with transaction.atomic():
            bug, _ = file_auto_bug_report(
                key=f"pipeline:data-repair:{name}",
                description="\n".join(
                    [
                        "Incidente de pipeline: data-repair",
                        f"La reparación de datos `{name}` falló en producción y se deshizo; "
                        "los datos siguen como estaban.",
                        "Error:",
                        "".join(traceback.format_exception_only(type(error), error)).strip()[:1500],
                    ]
                ),
                error_type="pipeline-incident",
                origin="ci",
            )
            # Like every pipeline incident: urgent, so the corrected repair ships right away. The
            # 10-minute sweep fires the fixer (Celery may not be up yet while the API migrates).
            if bug.severity != BugReport.Severity.BLOQUEANTE:
                bug.severity = BugReport.Severity.BLOQUEANTE
                bug.save(update_fields=["severity", "updated_at"])
    except Exception:
        logger.exception("data repair %s: could not file the incident", name)
