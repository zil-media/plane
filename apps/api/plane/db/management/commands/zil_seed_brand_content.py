# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Django imports
from django.core.management.base import BaseCommand
from django.db import transaction

# Module imports
from plane.authentication.utils.zil_provisioning import get_service_user
from plane.db.models import ZilBrandProject
from plane.utils.zil_client_portal import seed_brand_content


class Command(BaseCommand):
    help = (
        "Give every brand project its content calendar (states, network/format labels, 'Visible al "
        "cliente', the 'Calendario de contenidos' view) and its 'Cliente' pages folder. Idempotent: "
        "what exists by name is left as it is. The portals stay off."
    )

    def add_arguments(self, parser):
        parser.add_argument("--workspace", action="append", help="workspace slug (repeatable); default: all")

    def handle(self, *args, **options):
        mappings = ZilBrandProject.objects.filter(
            kind=ZilBrandProject.BRAND_KIND, project__deleted_at__isnull=True
        ).select_related("project")
        if options.get("workspace"):
            mappings = mappings.filter(workspace__slug__in=options["workspace"])
        owner = get_service_user()
        done = 0
        for mapping in mappings:
            with transaction.atomic():
                seed_brand_content(mapping.project, owner)
            done += 1
        self.stdout.write(f"{done} brand projects seeded")
