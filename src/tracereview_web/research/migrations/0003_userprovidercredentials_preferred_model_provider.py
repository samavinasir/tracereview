from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("research", "0002_researchrun"),
    ]

    operations = [
        migrations.AddField(
            model_name="userprovidercredentials",
            name="preferred_model_provider",
            field=models.CharField(default="auto", max_length=20),
        ),
    ]
