from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
from django.db.models import F
from decimal import Decimal


class Migration(migrations.Migration):
    dependencies = [
        ("sales", "0001_initial"),
        ("accounting", "0007_fx_settlement_record"),
        ("currencies", "0001_initial"),
        ("inventory", "0005_stockmovement_source_party"),
        ("warehouses", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="SalesReturn",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("document_number", models.CharField(max_length=30, unique=True)),
                ("return_date", models.DateField()),
                ("quantity", models.PositiveIntegerField()),
                ("entitlement_amount", models.DecimalField(decimal_places=2, max_digits=20)),
                ("refundable_amount", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=20)),
                ("status", models.CharField(choices=[("POSTED", "Posted"), ("REVERSED", "Reversed")], default="POSTED", max_length=10)),
                ("reason", models.CharField(max_length=500)),
                ("idempotency_key", models.CharField(max_length=128, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="sales_returns_created", to=settings.AUTH_USER_MODEL)),
                ("entitlement_currency", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="sales_return_entitlements", to="currencies.currency")),
                ("entitlement_journal", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="sales_return_entitlements", to="accounting.journalentry")),
                ("inventory_return", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="sales_return", to="inventory.inventoryreturn")),
                ("sale", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="sales_returns", to="sales.sale")),
                ("sale_line", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="sales_returns", to="sales.saleline")),
                ("warehouse", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="sales_returns", to="warehouses.warehouse")),
            ],
            options={"ordering": ["return_date", "document_number"]},
        ),
        migrations.AddField(
            model_name="salesreturn",
            name="cogs_journal",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="sales_return_cogs", to="accounting.journalentry"),
        ),
        migrations.CreateModel(
            name="Refund",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("document_number", models.CharField(max_length=30, unique=True)),
                ("refund_date", models.DateField()),
                ("entitlement_amount", models.DecimalField(decimal_places=2, max_digits=20)),
                ("refund_amount", models.DecimalField(decimal_places=2, max_digits=20)),
                ("agreed_rate", models.DecimalField(decimal_places=8, max_digits=20)),
                ("rate_direction", models.CharField(max_length=80)),
                ("status", models.CharField(choices=[("POSTED", "Posted"), ("REVERSED", "Reversed")], default="POSTED", max_length=10)),
                ("reason", models.CharField(max_length=500)),
                ("idempotency_key", models.CharField(max_length=128, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="refunds_created", to=settings.AUTH_USER_MODEL)),
                ("entitlement_currency", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="refund_entitlements", to="currencies.currency")),
                ("journal_entry", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="refunds", to="accounting.journalentry")),
                ("refund_currency", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="refund_payments", to="currencies.currency")),
                ("sales_return", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="refunds", to="sales.salesreturn")),
            ],
            options={"ordering": ["refund_date", "document_number"]},
        ),
        migrations.CreateModel(
            name="CrossCurrencyRefund",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("entitlement_amount", models.DecimalField(decimal_places=2, max_digits=20)),
                ("refund_amount", models.DecimalField(decimal_places=2, max_digits=20)),
                ("agreed_rate", models.DecimalField(decimal_places=8, max_digits=20)),
                ("rate_direction", models.CharField(max_length=80)),
                ("status", models.CharField(choices=[("POSTED", "Posted"), ("REVERSED", "Reversed")], default="POSTED", max_length=10)),
                ("idempotency_key", models.CharField(max_length=128, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("entitlement_currency", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="cross_refunds_as_entitlement", to="currencies.currency")),
                ("entitlement_journal", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="cross_currency_refund_entitlement", to="accounting.journalentry")),
                ("refund", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="cross_currency_refund", to="sales.refund")),
                ("refund_currency", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="cross_refunds_as_payment", to="currencies.currency")),
                ("cash_journal", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="cross_currency_refund_cash", to="accounting.journalentry")),
            ],
            options={"ordering": ["id"]},
        ),
        migrations.AddConstraint(
            model_name="salesreturn",
            constraint=models.CheckConstraint(condition=models.Q(quantity__gt=0), name="sales_return_qty_gt0"),
        ),
        migrations.AddConstraint(
            model_name="salesreturn",
            constraint=models.CheckConstraint(condition=models.Q(entitlement_amount__gt=0), name="sales_return_entitlement_gt0"),
        ),
        migrations.AddConstraint(
            model_name="salesreturn",
            constraint=models.CheckConstraint(condition=models.Q(refundable_amount__gte=0), name="sales_return_refundable_gte0"),
        ),
        migrations.AddConstraint(
            model_name="salesreturn",
            constraint=models.CheckConstraint(condition=models.Q(refundable_amount__lte=F("entitlement_amount")), name="sales_return_refundable_lte_entitlement"),
        ),
        migrations.AddConstraint(
            model_name="refund",
            constraint=models.CheckConstraint(condition=models.Q(entitlement_amount__gt=0), name="refund_entitlement_gt0"),
        ),
        migrations.AddConstraint(
            model_name="refund",
            constraint=models.CheckConstraint(condition=models.Q(refund_amount__gt=0), name="refund_amount_gt0"),
        ),
        migrations.AddConstraint(
            model_name="refund",
            constraint=models.CheckConstraint(condition=models.Q(agreed_rate__gt=0), name="refund_rate_gt0"),
        ),
        migrations.AddConstraint(
            model_name="crosscurrencyrefund",
            constraint=models.CheckConstraint(condition=models.Q(entitlement_amount__gt=0), name="cross_refund_entitlement_gt0"),
        ),
        migrations.AddConstraint(
            model_name="crosscurrencyrefund",
            constraint=models.CheckConstraint(condition=models.Q(refund_amount__gt=0), name="cross_refund_amount_gt0"),
        ),
        migrations.AddConstraint(
            model_name="crosscurrencyrefund",
            constraint=models.CheckConstraint(condition=models.Q(agreed_rate__gt=0), name="cross_refund_rate_gt0"),
        ),
    ]
