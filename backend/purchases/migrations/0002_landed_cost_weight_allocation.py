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
        migrations.AddConstraint(
            model_name="purchaseline",
            constraint=models.CheckConstraint(condition=models.Q(measured_weight_kg__isnull=True) | models.Q(measured_weight_kg__gt=0), name="purchase_line_weight_kg_gt0"),
        ),
        migrations.AddConstraint(
            model_name="purchaseline",
            constraint=models.CheckConstraint(condition=models.Q(freight_allocated__gte=0), name="purchase_line_freight_allocated_gte0"),
        ),
    ]
