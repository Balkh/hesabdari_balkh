from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("customer_custody", "0001_initial"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="customercustodyevent",
            constraint=models.UniqueConstraint(
                fields=("reversal_of",),
                condition=models.Q(reversal_of__isnull=False),
                name="custody_one_reversal_per_event",
            ),
        ),
    ]
