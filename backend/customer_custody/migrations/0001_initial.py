from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("sales", "0004_phase11_sales_return_reversal"),
    ]

    operations = [
        migrations.CreateModel(
            name="CustomerOwnershipEntitlement",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("quantity", models.PositiveIntegerField()),
                ("ownership_date", models.DateField()),
                ("status", models.CharField(choices=[("ACTIVE", "Active"), ("REVERSED", "Reversed")], default="ACTIVE", max_length=10)),
                ("idempotency_key", models.CharField(max_length=128, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="customer_ownership_entitlements_created", to=settings.AUTH_USER_MODEL)),
                ("customer", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="customer_ownership_entitlements", to="parties.party")),
                ("product", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="customer_ownership_entitlements", to="products.product")),
                ("sale_line", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="customer_ownership_entitlement", to="sales.saleline")),
            ],
            options={"ordering": ["ownership_date", "id"]},
        ),
        migrations.CreateModel(
            name="CustomerCustodyEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("event_type", models.CharField(choices=[("PLACED", "Placed into Customer Custody"), ("RELEASED", "Released from Customer Custody"), ("RELEASE_REVERSAL", "Release Reversal"), ("PLACEMENT_REVERSAL", "Placement Reversal")], max_length=20)),
                ("quantity", models.PositiveIntegerField()),
                ("event_date", models.DateField()),
                ("reference", models.CharField(max_length=200)),
                ("idempotency_key", models.CharField(max_length=128, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="customer_custody_events_created", to=settings.AUTH_USER_MODEL)),
                ("customer", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="customer_custody_events", to="parties.party")),
                ("entitlement", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="custody_events", to="customer_custody.customerownershipentitlement")),
                ("product", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="customer_custody_events", to="products.product")),
                ("reversal_of", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="reversal_events", to="customer_custody.customercustodyevent")),
                ("warehouse", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="customer_custody_events", to="warehouses.warehouse")),
            ],
            options={"ordering": ["event_date", "id"]},
        ),
        migrations.AddConstraint(
            model_name="customerownershipentitlement",
            constraint=models.CheckConstraint(condition=models.Q(quantity__gt=0), name="custody_ownership_qty_gt0"),
        ),
        migrations.AddConstraint(
            model_name="customercustodyevent",
            constraint=models.CheckConstraint(condition=models.Q(quantity__gt=0), name="custody_event_qty_gt0"),
        ),
    ]
