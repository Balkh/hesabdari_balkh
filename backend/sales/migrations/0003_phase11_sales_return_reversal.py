from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("sales", "0003_phase11_returns_refunds"),
    ]

    operations = [
        migrations.CreateModel(
            name="SalesReturnReversal",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("document_number", models.CharField(max_length=30, unique=True)),
                ("reversal_date", models.DateField()),
                ("reason", models.CharField(max_length=500)),
                ("idempotency_key", models.CharField(max_length=128, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("created_by", models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name="sales_return_reversals_created", to=settings.AUTH_USER_MODEL,
                )),
                ("cogs_reversal_journal", models.OneToOneField(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="sales_return_cogs_reversal", to="accounting.journalentry",
                )),
                ("entitlement_reversal_journal", models.OneToOneField(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="sales_return_entitlement_reversal", to="accounting.journalentry",
                )),
                ("inventory_movement", models.OneToOneField(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="sales_return_reversal", to="inventory.stockmovement",
                )),
                ("sales_return", models.OneToOneField(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="reversal", to="sales.salesreturn",
                )),
            ],
            options={"ordering": ["reversal_date", "document_number"]},
        ),
    ]
