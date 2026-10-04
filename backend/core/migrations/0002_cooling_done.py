from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="clothroll",
            name="cooling_done",
            field=models.BooleanField(default=False),
        ),
    ]
