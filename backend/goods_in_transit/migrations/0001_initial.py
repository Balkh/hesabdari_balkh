from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("accounting", "0008_cross_currency_clearing_account"),
        ("currencies", "0001_initial"),
        ("inventory", "0001_initial"),
        ("parties", "0001_initial"),
        ("products", "0001_initial"),
        ("purchases", "0002_purchasereturn"),
        ("warehouses", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="GoodsInTransitLot",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("original_quantity", models.PositiveIntegerField()),
                ("remaining_quantity", models.PositiveIntegerField()),
                ("unit_cost", models.DecimalField(decimal_places=4, max_digits=20)),
                ("rate", models.DecimalField(decimal_places=4, max_digits=20)),
                ("rate_date", models.DateField()),
                ("ownership_date", models.DateField()),
                ("status", models.CharField(choices=[("OPEN", "Open"), ("CLOSED", "Closed"), ("REVERSED", "Reversed")], default="OPEN", max_length=10)),
                ("idempotency_key", models.CharField(max_length=128, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="goods_in_transit_lots_created", to=settings.AUTH_USER_MODEL)),
                ("currency", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="goods_in_transit_lots", to="currencies.currency")),
                ("destination_warehouse", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="goods_in_transit_lots", to="warehouses.warehouse")),
                ("journal_entry", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="goods_in_transit_lot", to="accounting.journalentry")),
                ("product", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="goods_in_transit_lots", to="products.product")),
                ("purchase", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="transit_lots", to="purchases.purchase")),
                ("purchase_line", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="transit_lot", to="purchases.purchaseline")),
                ("supplier", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="goods_in_transit_lots", to="parties.party")),
            ],
            options={"ordering": ["ownership_date", "id"]},
        ),
        migrations.CreateModel(
            name="TransitReceipt",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("quantity", models.PositiveIntegerField()),
                ("receipt_date", models.DateField()),
                ("idempotency_key", models.CharField(max_length=128, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="transit_receipts_created", to=settings.AUTH_USER_MODEL)),
                ("journal_entry", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="transit_receipt", to="accounting.journalentry")),
                ("lot", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="receipts", to="goods_in_transit.goodsintransitlot")),
                ("stock_movement", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="transit_receipt", to="inventory.stockmovement")),
                ("warehouse", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="transit_receipts", to="warehouses.warehouse")),
            ],
            options={"ordering": ["receipt_date", "id"]},
        ),
        migrations.AddConstraint(
            model_name="goodsintransitlot",
            constraint=models.CheckConstraint(condition=models.Q(original_quantity__gt=0), name="transit_lot_original_gt0"),
        ),
        migrations.AddConstraint(
            model_name="goodsintransitlot",
            constraint=models.CheckConstraint(condition=models.Q(remaining_quantity__lte=models.F("original_quantity")), name="transit_lot_remaining_lte_original"),
        ),
        migrations.AddConstraint(
            model_name="goodsintransitlot",
            constraint=models.CheckConstraint(condition=models.Q(unit_cost__gte=0), name="transit_lot_cost_gte0"),
        ),
        migrations.AddConstraint(
            model_name="goodsintransitlot",
            constraint=models.CheckConstraint(condition=models.Q(rate__gt=0), name="transit_lot_rate_gt0"),
        ),
        migrations.AddConstraint(
            model_name="transitreceipt",
            constraint=models.CheckConstraint(condition=models.Q(quantity__gt=0), name="transit_receipt_qty_gt0"),
        ),
    ]
