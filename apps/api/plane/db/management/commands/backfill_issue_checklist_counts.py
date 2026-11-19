# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Django imports
from django.core.management.base import BaseCommand

# Module imports
from plane.db.models import Issue
from plane.utils.description_checklist import count_checklist


class Command(BaseCommand):
    help = "Recount checklist_total / checklist_completed from description_html for existing work items"

    def add_arguments(self, parser):
        parser.add_argument("--batch-size", type=int, default=500)

    def handle(self, *args, **options):
        batch_size = options["batch_size"]
        updated = 0
        last_id = None

        # Only rows whose description has a task list, or whose stored counts are stale non-zero.
        # bulk_update writes just the two columns: updated_at and activity stay untouched.
        base = Issue.all_objects.filter(description_html__contains="taskItem") | Issue.all_objects.filter(
            checklist_total__gt=0
        )
        base = base.order_by("id").only("id", "description_html", "checklist_total", "checklist_completed")

        while True:
            qs = base if last_id is None else base.filter(id__gt=last_id)
            batch = list(qs[:batch_size])
            if not batch:
                break
            last_id = batch[-1].id

            changed = []
            for issue in batch:
                total, completed = count_checklist(issue.description_html)
                if (total, completed) != (issue.checklist_total, issue.checklist_completed):
                    issue.checklist_total = total
                    issue.checklist_completed = completed
                    changed.append(issue)

            if changed:
                Issue.all_objects.bulk_update(changed, ["checklist_total", "checklist_completed"])
                updated += len(changed)

        self.stdout.write(self.style.SUCCESS(f"Updated checklist counts on {updated} work items"))
