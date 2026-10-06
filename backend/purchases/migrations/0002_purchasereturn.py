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
        ("purchases", "0001_initial"),
        ("warehouses", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="PurchaseReturn",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("document_number", models.CharField(max_length=30, unique=True)),
                ("return_date", models.DateField()),
                ("quantity", models.IntegerField()),
                ("amount", models.DecimalField(decimal_places=2, max_digits=20)),
                ("status", models.CharField(choices=[("POSTED", "Posted"), ("REVERSED", "Reversed")], default="POSTED", max_length=10)),
                ("reason", models.CharField(max_length=500)),
                ("idempotency_key", models.CharField(max_length=128, unique=True)),
                ("posted_at", models.DateTimeField(auto_now_add=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="purchase_returns_created", to=settings.AUTH_USER_MODEL)),
                ("currency", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="purchase_returns", to="currencies.currency")),
                ("inventory_return", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="purchase_financial_return", to="inventory.inventoryreturn")),
                ("journal_entry", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="purchase_return_document", to="accounting.journalentry")),
                ("purchase", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="purchase_returns", to="purchases.purchase")),
                ("supplier", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="purchase_returns", to="parties.party")),
                ("warehouse", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="purchase_returns", to="warehouses.warehouse")),
            ],
            options={"ordering": ["return_date", "document_number"]},
        ),
        migrations.CreateModel(
            name="PurchaseReturnReversal",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("reason", models.CharField(max_length=500)),
                ("idempotency_key", models.CharField(max_length=128, unique=True)),
                ("reversed_at", models.DateTimeField(auto_now_add=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="purchase_return_reversals_created", to=settings.AUTH_USER_MODEL)),
                ("journal_entry", models.OneToOneField(on_delete=django.db.models.PROTECT, related_name="purchase_return_reversal", to="accounting.journalentry")),
                ("purchase_return", models.OneToOneField(on_delete=django.db.models.PROTECT, related_name="reversal", to="purchases.purchasereturn")),
                ("stock_movement", models.OneToOneField(on_delete=django.db.models.PROTECT, related_name="purchase_return_reversal", to="inventory.stockmovement")),
            ],
        ),
        migrations.AddConstraint(
            model_name="purchasereturn",
            constraint=models.CheckConstraint(condition=models.Q(quantity__gt=0), name="purchase_return_qty_gt0"),
        ),
        migrations.AddConstraint(
            model_name="purchasereturn",
            constraint=models.CheckConstraint(condition=models.Q(amount__gt=0), name="purchase_return_amount_gt0"),
        ),
    ]
