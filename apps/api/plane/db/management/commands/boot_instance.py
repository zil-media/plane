# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Django imports
from django.core.management import BaseCommand, call_command


class Command(BaseCommand):
    help = "API boot steps in one process (register, configure, bucket, cache) instead of one Django start each"

    def add_arguments(self, parser):
        parser.add_argument("machine_signature", type=str, help="Machine signature")

    def handle(self, *args, **options):
        # Each step used to be its own `python manage.py`, paying the ~2 s Django start four times
        # while the API was down during a deploy. Same steps, same order, same failure behaviour:
        # an exception stops the boot.
        call_command("register_instance", options["machine_signature"])
        call_command("configure_instance")
        call_command("create_bucket")
        call_command("clear_cache")
