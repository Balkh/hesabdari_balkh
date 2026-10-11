from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("purchases", "0001_initial")]

    operations = [
        migrations.AddField(
            model_name="purchaseline",
            name="measured_weight_kg",
            field=models.DecimalField(blank=True, decimal_places=4, max_digits=20, null=True),
        ),
        migrations.AddField(
            model_name="purchaseline",
            name="freight_allocated",
            field=models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=20),
        ),
    ]
