# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
import json

# Django imports
from django.core.management.base import BaseCommand, CommandError

# Module imports
from plane.utils.zil_page_move import load_client_brand_map, migrate_client_pages


class Command(BaseCommand):
    help = (
        "Move each Zil client folder to its brand's project (clients with several brands go to the "
        "private 'Migración' project) and drop the 'Clientes' folder. Dry run unless --apply: "
        "everything is done inside a transaction that is rolled back, and the report says what would move."
    )

    def add_arguments(self, parser):
        parser.add_argument("--map", required=True, help="JSON from Zil's exportClientBrandMap.js")
        parser.add_argument("--workspace", action="append", help="workspace slug (repeatable); default: all")
        parser.add_argument("--apply", action="store_true", help="keep the changes (default: dry run)")
        parser.add_argument("--out", help="also write the report to this JSON file")

    def handle(self, *args, **options):
        try:
            client_brands = load_client_brand_map(options["map"])
        except (OSError, ValueError) as e:
            raise CommandError(f"cannot read the client → brand map: {e}")

        report = migrate_client_pages(client_brands, options.get("workspace"), apply=options["apply"])
        text = json.dumps(report, ensure_ascii=False, indent=2, default=str)
        if options.get("out"):
            with open(options["out"], "w", encoding="utf-8") as handle:
                handle.write(text)
        self.stdout.write(text)
        mode = "APPLIED" if report["applied"] else "DRY RUN (nothing kept)"
        for ws in report["workspaces"]:
            totals = ws["totals"]
            self.stdout.write(
                f"[{mode}] {ws['workspace']}: {totals.get('folders', 0)} folders, {totals.get('pages', 0)} pages, "
                f"{totals.get('assets', 0)} files moved; {totals.get('to_migration', 0)} to Migración; "
                f"{totals.get('skipped', 0)} skipped; {totals.get('unreachable_private', 0)} private pages to review"
            )
