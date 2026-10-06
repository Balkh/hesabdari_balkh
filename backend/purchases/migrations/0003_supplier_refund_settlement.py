from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("accounting", "0008_cross_currency_clearing_account"),
        ("currencies", "0001_initial"),
        ("purchases", "0002_purchasereturn"),
    ]

    operations = [
        migrations.CreateModel(
            name="SupplierRefund",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("document_number", models.CharField(max_length=30, unique=True)),
                ("refund_date", models.DateField()),
                ("claim_amount", models.DecimalField(decimal_places=2, max_digits=20)),
                ("refund_amount", models.DecimalField(decimal_places=2, max_digits=20)),
                ("agreed_rate", models.DecimalField(decimal_places=8, max_digits=20)),
                ("rate_direction", models.CharField(max_length=80)),
                ("status", models.CharField(choices=[("POSTED", "Posted"), ("REVERSED", "Reversed")], default="POSTED", max_length=10)),
                ("reason", models.CharField(max_length=500)),
                ("idempotency_key", models.CharField(max_length=128, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("claim_currency", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="supplier_refund_claims", to="currencies.currency")),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="supplier_refunds_created", to=settings.AUTH_USER_MODEL)),
                ("journal_entry", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="supplier_refunds", to="accounting.journalentry")),
                ("purchase_return", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="refunds", to="purchases.purchasereturn")),
                ("refund_currency", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="supplier_refund_cash", to="currencies.currency")),
            ],
            options={"ordering": ["refund_date", "document_number"]},
        ),
        migrations.CreateModel(
            name="CrossCurrencySupplierRefund",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("claim_amount", models.DecimalField(decimal_places=2, max_digits=20)),
                ("refund_amount", models.DecimalField(decimal_places=2, max_digits=20)),
                ("agreed_rate", models.DecimalField(decimal_places=8, max_digits=20)),
                ("rate_direction", models.CharField(max_length=80)),
                ("status", models.CharField(choices=[("POSTED", "Posted"), ("REVERSED", "Reversed")], default="POSTED", max_length=10)),
                ("idempotency_key", models.CharField(max_length=128, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("cash_journal", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="cross_currency_supplier_refund_cash", to="accounting.journalentry")),
                ("claim_currency", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="cross_supplier_refunds_as_claim", to="currencies.currency")),
                ("claim_journal", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="cross_currency_supplier_refund_claim", to="accounting.journalentry")),
                ("refund", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="cross_currency_refund", to="purchases.supplierrefund")),
                ("refund_currency", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="cross_supplier_refunds_as_cash", to="currencies.currency")),
            ],
            options={"ordering": ["id"]},
        ),
        migrations.CreateModel(
            name="SupplierRefundReversal",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("reason", models.CharField(max_length=500)),
                ("idempotency_key", models.CharField(max_length=128, unique=True)),
                ("reversed_at", models.DateTimeField(auto_now_add=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="supplier_refund_reversals_created", to=settings.AUTH_USER_MODEL)),
                ("cross_currency", models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="reversal", to="purchases.crosscurrencysupplierrefund")),
                ("journal_entry", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="supplier_refund_reversal", to="accounting.journalentry")),
                ("refund", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="reversal", to="purchases.supplierrefund")),
            ],
        ),
        migrations.AddConstraint(
            model_name="supplierrefund",
            constraint=models.CheckConstraint(condition=models.Q(claim_amount__gt=0), name="supplier_refund_claim_amount_gt0"),
        ),
        migrations.AddConstraint(
            model_name="supplierrefund",
            constraint=models.CheckConstraint(condition=models.Q(refund_amount__gt=0), name="supplier_refund_amount_gt0"),
        ),
        migrations.AddConstraint(
            model_name="supplierrefund",
            constraint=models.CheckConstraint(condition=models.Q(agreed_rate__gt=0), name="supplier_refund_rate_gt0"),
        ),
        migrations.AddConstraint(
            model_name="crosscurrencysupplierrefund",
            constraint=models.CheckConstraint(condition=models.Q(claim_amount__gt=0), name="cross_supplier_refund_claim_gt0"),
        ),
        migrations.AddConstraint(
            model_name="crosscurrencysupplierrefund",
            constraint=models.CheckConstraint(condition=models.Q(refund_amount__gt=0), name="cross_supplier_refund_amount_gt0"),
        ),
        migrations.AddConstraint(
            model_name="crosscurrencysupplierrefund",
            constraint=models.CheckConstraint(condition=models.Q(agreed_rate__gt=0), name="cross_supplier_refund_rate_gt0"),
        ),
    ]
