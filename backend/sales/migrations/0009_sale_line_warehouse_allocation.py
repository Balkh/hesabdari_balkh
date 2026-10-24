from decimal import Decimal
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounting", "0001_initial"),
        ("inventory", "0005_stockmovement_source_party"),
        ("sales", "0008_negative_cogs_receipt_allocation"),
        ("warehouses", "0001_initial"),
    ]
    operations = [
        migrations.CreateModel(
            name="SaleLineWarehouseAllocation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("quantity", models.PositiveIntegerField()),
                ("unit_cost_afn", models.DecimalField(decimal_places=4, default=Decimal("0.0000"), max_digits=20)),
                ("idempotency_key", models.CharField(max_length=128, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("cogs_journal", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="sale_line_allocation", to="accounting.journalentry", null=True, blank=True)),
                ("inventory_account", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="sale_line_allocations", to="accounting.account", null=True, blank=True)),
                ("sale_line", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="warehouse_allocations", to="sales.saleline")),
                ("stock_movement", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="sale_line_allocation", to="inventory.stockmovement", null=True, blank=True)),
                ("warehouse", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="sale_line_allocations", to="warehouses.warehouse")),
            ],
            options={"ordering": ["id"]},
        ),
        migrations.AddConstraint(model_name="salelinewarehouseallocation", constraint=models.CheckConstraint(condition=models.Q(quantity__gt=0), name="sale_line_alloc_qty_gt0")),
        migrations.AddConstraint(model_name="salelinewarehouseallocation", constraint=models.CheckConstraint(condition=models.Q(unit_cost_afn__gte=0), name="sale_line_alloc_cost_gte0")),
        migrations.AddConstraint(model_name="salelinewarehouseallocation", constraint=models.UniqueConstraint(fields=("sale_line", "warehouse"), name="uniq_sale_line_warehouse_alloc")),
        migrations.AddField(model_name="negativecogsobligation", name="sale_allocation", field=models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="negative_cogs_obligation", to="sales.salelinewarehouseallocation")),
        migrations.AlterField(model_name="negativecogsobligation", name="warehouse_check", field=models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="negative_cogs_obligation", to="sales.warehousecheck")),
    ]
