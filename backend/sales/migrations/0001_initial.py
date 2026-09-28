from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
from decimal import Decimal


class Migration(migrations.Migration):
    initial = True
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("accounting", "0007_fx_settlement_record"),
        ("currencies", "0001_initial"),
        ("parties", "0001_initial"),
        ("products", "0001_initial"),
        ("warehouses", "0001_initial"),
        ("inventory", "0005_stockmovement_source_party"),
        ("uom", "0001_initial"),
    ]
    operations = [
        migrations.CreateModel(name="Sale", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("document_number", models.CharField(max_length=30, unique=True)),
            ("sale_date", models.DateField()),
            ("exchange_rate", models.DecimalField(decimal_places=4, max_digits=20)),
            ("rate_date", models.DateField()),
            ("sale_type", models.CharField(choices=[("AVAILABLE", "Available"), ("FUTURE", "Future")], default="AVAILABLE", max_length=10)),
            ("channel", models.CharField(choices=[("WHOLESALE", "Wholesale"), ("RETAIL", "Retail")], max_length=10)),
            ("payment_mode", models.CharField(choices=[("CASH", "Cash"), ("CREDIT", "Credit")], max_length=8)),
            ("subtotal", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=20)),
            ("total_discount", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=20)),
            ("total", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=20)),
            ("status", models.CharField(choices=[("DRAFT", "Draft"), ("FINALIZED", "Finalized")], default="DRAFT", max_length=10)),
            ("finalized_at", models.DateTimeField(blank=True, null=True)),
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="sales_created", to=settings.AUTH_USER_MODEL)),
            ("currency", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="sales", to="currencies.currency")),
            ("customer", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="sales", to="parties.party")),
            ("journal_entry", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="sales", to="accounting.journalentry")),
        ], options={"ordering": ["sale_date", "document_number"]}),
        migrations.CreateModel(name="SaleLine", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("quantity", models.IntegerField()), ("unit_price", models.DecimalField(decimal_places=4, max_digits=20)),
            ("discount", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=20)),
            ("line_total", models.DecimalField(decimal_places=2, max_digits=20)), ("net_total", models.DecimalField(decimal_places=2, max_digits=20)),
            ("sale", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="lines", to="sales.sale")),
            ("product", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="sale_lines", to="products.product")),
            ("unit", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="sale_lines", to="uom.unitofmeasure")),
        ], options={"ordering": ["id"], "constraints": [models.CheckConstraint(condition=models.Q(quantity__gt=0), name="sale_line_qty_gt0")]}),
        migrations.CreateModel(name="WarehouseCheck", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")), ("number", models.CharField(max_length=30, unique=True)),
            ("quantity", models.IntegerField()), ("status", models.CharField(choices=[("DRAFT", "Draft"), ("FINALIZED", "Finalized")], default="DRAFT", max_length=10)),
            ("finalized_at", models.DateTimeField(blank=True, null=True)), ("created_at", models.DateTimeField(auto_now_add=True)),
            ("cogs_journal", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="warehouse_check_cogs", to="accounting.journalentry")),
            ("sale", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="warehouse_checks", to="sales.sale")),
            ("sale_line", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="warehouse_checks", to="sales.saleline")),
            ("stock_movement", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="warehouse_checks", to="inventory.stockmovement")),
            ("warehouse", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="warehouse_checks", to="warehouses.warehouse")),
        ], options={"ordering": ["number"], "constraints": [models.CheckConstraint(condition=models.Q(quantity__gt=0), name="warehouse_check_qty_gt0")]}),
        migrations.CreateModel(name="OwnershipEvent", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")), ("quantity", models.IntegerField()), ("created_at", models.DateTimeField(auto_now_add=True)),
            ("warehouse_check", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="ownership_event", to="sales.warehousecheck")),
            ("customer", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="ownership_events", to="parties.party")),
            ("product", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="ownership_events", to="products.product")),
            ("sale_line", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="ownership_events", to="sales.saleline")),
            ("warehouse", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="ownership_events", to="warehouses.warehouse")),
        ]),
        migrations.CreateModel(name="NegativeCOGSObligation", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")), ("original_quantity", models.PositiveIntegerField()), ("resolved_quantity", models.PositiveIntegerField(default=0)), ("temporary_unit_cost_afn", models.DecimalField(decimal_places=4, max_digits=20)), ("movement_date", models.DateField()), ("created_at", models.DateTimeField(auto_now_add=True)),
            ("movement", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="negative_cogs_obligation", to="inventory.stockmovement")),
            ("product", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="negative_cogs_obligations", to="products.product")),
            ("warehouse", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="negative_cogs_obligations", to="warehouses.warehouse")),
            ("warehouse_check", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="negative_cogs_obligation", to="sales.warehousecheck")),
        ], options={"ordering": ["movement_date", "id"]}),
        migrations.CreateModel(name="COGSAdjustment", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")), ("quantity", models.PositiveIntegerField()), ("actual_unit_cost_afn", models.DecimalField(decimal_places=4, max_digits=20)), ("temporary_unit_cost_afn", models.DecimalField(decimal_places=4, max_digits=20)), ("difference", models.DecimalField(decimal_places=2, max_digits=20)), ("created_at", models.DateTimeField(auto_now_add=True)),
            ("journal_entry", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="cogs_adjustment", to="accounting.journalentry")),
            ("obligation", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="adjustments", to="sales.negativecogsobligation")),
            ("receipt_movement", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="cogs_adjustments", to="inventory.stockmovement")),
        ]),
    ]
