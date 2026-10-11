import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounting", "0007_fx_settlement_record"),
        ("inventory", "0005_stockmovement_source_party"),
        ("sales", "0006_transit_sales_return"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="WarehouseCheckReversal",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("reversal_date", models.DateField()),
                ("reason", models.CharField(max_length=500)),
                ("idempotency_key", models.CharField(max_length=128, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="warehouse_check_reversals_created", to=settings.AUTH_USER_MODEL)),
                ("warehouse_check", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="reversal", to="sales.warehousecheck")),
            ],
            options={"ordering": ["reversal_date", "id"]},
        ),
    ]
