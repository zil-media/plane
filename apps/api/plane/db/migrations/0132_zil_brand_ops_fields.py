import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("db", "0131_issue_target_time"),
    ]

    operations = [
        migrations.AddField(
            model_name="zilbrandproject",
            name="community_manager",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="zil_brands_as_cm",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="zilbrandproject",
            name="leader",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="zil_brands_as_leader",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="zilbrandproject",
            name="materials_url",
            field=models.URLField(blank=True, default="", max_length=2048),
        ),
        migrations.AddField(
            model_name="zilbrandproject",
            name="finals_url",
            field=models.URLField(blank=True, default="", max_length=2048),
        ),
    ]
