from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("purchases", "0002_purchasereturn"),
    ]

    operations = [
        migrations.AddField(
            model_name="purchase",
            name="delivery_mode",
            field=models.CharField(
                choices=[
                    ("IMMEDIATE", "Immediate warehouse receipt"),
                    ("IN_TRANSIT", "Owned in transit"),
                ],
                default="IMMEDIATE",
                max_length=12,
            ),
        ),
    ]
