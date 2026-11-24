import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def leaders_to_units(apps, schema_editor):
    """Each brand's líderes become the Responsable of the units they work the brand in (one per unit)."""
    ZilBrandOps = apps.get_model("db", "ZilBrandOps")
    ZilBrandProject = apps.get_model("db", "ZilBrandProject")
    ZilBrandResponsible = apps.get_model("db", "ZilBrandResponsible")
    ProjectMember = apps.get_model("db", "ProjectMember")
    for ops in ZilBrandOps.objects.filter(deleted_at__isnull=True):
        leaders = list(ops.leaders.order_by("display_name", "id").values_list("id", flat=True))
        if not leaders:
            continue
        mappings = ZilBrandProject.objects.filter(
            zil_brand_id=ops.zil_brand_id, kind="brand", deleted_at__isnull=True, project__deleted_at__isnull=True
        )
        for mapping in mappings:
            on_project = set(
                ProjectMember.objects.filter(
                    project_id=mapping.project_id, member_id__in=leaders, is_active=True, deleted_at__isnull=True
                ).values_list("member_id", flat=True)
            )
            leader = next((pk for pk in leaders if pk in on_project), None)
            if leader is None:
                continue
            ZilBrandResponsible.objects.get_or_create(
                zil_brand_id=ops.zil_brand_id,
                workspace_id=mapping.workspace_id,
                deleted_at__isnull=True,
                defaults={"member_id": leader},
            )


class Migration(migrations.Migration):
    dependencies = [
        ("db", "0138_bug_report_retry"),
    ]

    operations = [
        migrations.CreateModel(
            name="ZilBrandResponsible",
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
                (
                    "workspace",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="zil_brand_responsibles",
                        to="db.workspace",
                    ),
                ),
                (
                    "member",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="zil_brand_responsible_of",
                        to=settings.AUTH_USER_MODEL,
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
                "verbose_name": "Zil Brand Responsible",
                "verbose_name_plural": "Zil Brand Responsibles",
                "db_table": "zil_brand_responsibles",
                "ordering": ("-created_at",),
                "constraints": [
                    models.UniqueConstraint(
                        condition=models.Q(deleted_at__isnull=True),
                        fields=("zil_brand_id", "workspace"),
                        name="zil_brand_responsible_unique_unit",
                    )
                ],
            },
        ),
        migrations.RunPython(leaders_to_units, migrations.RunPython.noop),
        migrations.RemoveField(model_name="zilbrandops", name="leaders"),
    ]
