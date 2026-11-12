import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def move_to_brand(apps, schema_editor):
    """Each workspace's CMs, líderes and links, merged into the one shared row of their brand."""
    ZilBrandProject = apps.get_model("db", "ZilBrandProject")
    ZilBrandOps = apps.get_model("db", "ZilBrandOps")
    mappings = ZilBrandProject.objects.filter(kind="brand", deleted_at__isnull=True).exclude(zil_brand_id="")
    for mapping in mappings.order_by("created_at"):
        cms = list(mapping.community_managers.values_list("id", flat=True))
        leaders = list(mapping.leaders.values_list("id", flat=True))
        if not (cms or leaders or mapping.materials_links or mapping.finals_links):
            continue
        ops, _ = ZilBrandOps.objects.get_or_create(zil_brand_id=mapping.zil_brand_id, deleted_at__isnull=True)
        ops.community_managers.add(*cms)
        ops.leaders.add(*leaders)
        for field in ("materials_links", "finals_links"):
            merged = list(getattr(ops, field))
            merged += [link for link in getattr(mapping, field) if link not in merged]
            setattr(ops, field, merged)
        ops.save(update_fields=["materials_links", "finals_links"])


class Migration(migrations.Migration):
    dependencies = [
        ("db", "0135_pagezilclientlink_logo_url"),
    ]

    operations = [
        migrations.CreateModel(
            name="ZilBrandOps",
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
                ("zil_brand_id", models.CharField(max_length=24)),
                ("materials_links", models.JSONField(blank=True, default=list)),
                ("finals_links", models.JSONField(blank=True, default=list)),
                (
                    "community_managers",
                    models.ManyToManyField(blank=True, related_name="zil_brand_ops_as_cm", to=settings.AUTH_USER_MODEL),
                ),
                (
                    "leaders",
                    models.ManyToManyField(
                        blank=True, related_name="zil_brand_ops_as_leader", to=settings.AUTH_USER_MODEL
                    ),
                ),
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
            ],
            options={
                "verbose_name": "Zil Brand Ops",
                "verbose_name_plural": "Zil Brand Ops",
                "db_table": "zil_brand_ops",
                "ordering": ("-created_at",),
                "constraints": [
                    models.UniqueConstraint(
                        condition=models.Q(deleted_at__isnull=True),
                        fields=("zil_brand_id",),
                        name="zil_brand_ops_unique_brand",
                    )
                ],
            },
        ),
        migrations.RunPython(move_to_brand, migrations.RunPython.noop),
        migrations.RemoveField(model_name="zilbrandproject", name="community_managers"),
        migrations.RemoveField(model_name="zilbrandproject", name="leaders"),
        migrations.RemoveField(model_name="zilbrandproject", name="materials_links"),
        migrations.RemoveField(model_name="zilbrandproject", name="finals_links"),
    ]
