from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("db", "0134_merge_20261109_2221"),
    ]

    operations = [
        migrations.AddField(
            model_name="pagezilclientlink",
            name="logo_url",
            field=models.TextField(blank=True, default=""),
        ),
    ]
