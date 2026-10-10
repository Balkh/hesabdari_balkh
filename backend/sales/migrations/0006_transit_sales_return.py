import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0005_stockmovement_source_party"),
        ("sales", "0005_merge_phase11_sales"),
    ]

    operations = [
        migrations.AlterField(
            model_name="salesreturn",
            name="inventory_return",
            field=models.OneToOneField(
                blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name="sales_return", to="inventory.inventoryreturn",
            ),
        ),
        migrations.AddField(
            model_name="salesreturn",
            name="return_movement",
            field=models.OneToOneField(
                blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name="transit_sales_returns", to="inventory.stockmovement",
            ),
        ),
        migrations.AddConstraint(
            model_name="salesreturn",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(inventory_return__isnull=False, return_movement__isnull=True)
                    | models.Q(inventory_return__isnull=True, return_movement__isnull=False)
                ),
                name="sales_return_exactly_one_stock_source",
            ),
        ),
    ]
