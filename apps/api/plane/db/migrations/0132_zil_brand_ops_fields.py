from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("db", "0131_issue_target_time"),
    ]

    operations = [
        migrations.AddField(
            model_name="zilbrandproject",
            name="community_managers",
            field=models.ManyToManyField(blank=True, related_name="zil_brands_as_cm", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name="zilbrandproject",
            name="leaders",
            field=models.ManyToManyField(blank=True, related_name="zil_brands_as_leader", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name="zilbrandproject",
            name="materials_links",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="zilbrandproject",
            name="finals_links",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
