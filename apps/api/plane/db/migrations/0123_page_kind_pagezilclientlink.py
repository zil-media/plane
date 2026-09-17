# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):
    dependencies = [
        ("db", "0122_importjob"),
    ]

    operations = [
        migrations.AddField(
            model_name="page",
            name="kind",
            field=models.CharField(
                choices=[("page", "Page"), ("folder", "Folder")],
                db_index=True,
                default="page",
                max_length=16,
            ),
        ),
        migrations.AddIndex(
            model_name="page",
            index=models.Index(fields=["parent", "sort_order"], name="page_parent_sort_idx"),
        ),
        migrations.CreateModel(
            name="PageZilClientLink",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Created At")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Last Modified At")),
                ("deleted_at", models.DateTimeField(blank=True, null=True, verbose_name="Deleted At")),
                (
                    "id",
                    models.UUIDField(
                        db_index=True,
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                        unique=True,
                    ),
                ),
                ("zil_client_id", models.CharField(max_length=24)),
                ("alias", models.CharField(blank=True, default="", max_length=255)),
                ("company_name", models.CharField(blank=True, default="", max_length=255)),
                ("lifecycle_status", models.CharField(blank=True, default="", max_length=32)),
                ("business_unit_slug", models.CharField(blank=True, default="", max_length=64)),
                ("synced_at", models.DateTimeField(blank=True, null=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(class)s_created_by",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Created By",
                    ),
                ),
                (
                    "updated_by",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(class)s_updated_by",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Last Modified By",
                    ),
                ),
                (
                    "page",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="zil_client_link",
                        to="db.page",
                    ),
                ),
                (
                    "project",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="page_zil_client_links",
                        to="db.project",
                    ),
                ),
                (
                    "workspace",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="page_zil_client_links",
                        to="db.workspace",
                    ),
                ),
            ],
            options={
                "verbose_name": "Page Zil Client Link",
                "verbose_name_plural": "Page Zil Client Links",
                "db_table": "page_zil_client_links",
                "ordering": ("-created_at",),
                "indexes": [models.Index(fields=["workspace", "zil_client_id"], name="pzcl_ws_client_idx")],
                "constraints": [
                    models.UniqueConstraint(
                        condition=models.Q(("deleted_at__isnull", True)),
                        fields=("project", "zil_client_id"),
                        name="page_zil_client_unique_per_project",
                    )
                ],
            },
        ),
    ]
