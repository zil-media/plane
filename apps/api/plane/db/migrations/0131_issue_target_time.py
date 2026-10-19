from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("db", "0130_zil_brand_projects"),
    ]

    operations = [
        migrations.AddField(
            model_name="issue",
            name="target_time",
            field=models.TimeField(blank=True, null=True),
        ),
    ]
