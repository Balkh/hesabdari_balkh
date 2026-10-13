import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0005_stockmovement_source_party"),
        ("sales", "0007_warehouse_check_reversal"),
    ]

    operations = [
        migrations.CreateModel(
            name="NegativeCOGSReceiptAllocation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("quantity", models.PositiveIntegerField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("obligation", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="receipt_allocations",
                    to="sales.negativecogsobligation",
                )),
                ("receipt_movement", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="negative_cogs_receipt_allocations",
                    to="inventory.stockmovement",
                )),
            ],
            options={"ordering": ["id"]},
        ),
        migrations.AddConstraint(
            model_name="negativecogsreceiptallocation",
            constraint=models.CheckConstraint(
                condition=models.Q(("quantity__gt", 0)),
                name="negative_cogs_receipt_alloc_qty_gt0",
            ),
        ),
        migrations.AddConstraint(
            model_name="negativecogsreceiptallocation",
            constraint=models.UniqueConstraint(
                fields=("obligation", "receipt_movement"),
                name="uniq_negative_cogs_receipt_alloc",
            ),
        ),
    ]
