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
        ("payments", "0001_initial"),
        ("sales", "0001_initial"),
    ]
    operations = [
        migrations.CreateModel(
            name="CustomerAllocation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("requested_amount", models.DecimalField(decimal_places=2, max_digits=20)),
                ("amount", models.DecimalField(decimal_places=2, max_digits=20)),
                ("credit_amount", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=20)),
                ("idempotency_key", models.CharField(max_length=128, unique=True)),
                ("allocated_at", models.DateTimeField(auto_now_add=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="customer_allocations_created", to=settings.AUTH_USER_MODEL)),
                ("currency", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="customer_allocations", to="currencies.currency")),
                ("journal_entry", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="allocation_adjustments", to="accounting.journalentry")),
                ("payment", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="allocations", to="payments.payment")),
                ("sale", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="customer_allocations", to="sales.sale")),
            ],
            options={"ordering": ["id"]},
        ),
        migrations.CreateModel(
            name="CustomerAllocationReversal",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("reason", models.CharField(max_length=500)),
                ("reversed_at", models.DateTimeField(auto_now_add=True)),
                ("idempotency_key", models.CharField(max_length=128, unique=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="customer_allocation_reversals_created", to=settings.AUTH_USER_MODEL)),
                ("allocation", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="reversal", to="allocations.customerallocation")),
                ("journal_entry", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="allocation_reversals", to="accounting.journalentry")),
            ],
            options={"ordering": ["id"]},
        ),
        migrations.AddConstraint(
            model_name="customerallocation",
            constraint=models.CheckConstraint(condition=models.Q(requested_amount__gt=0), name="allocation_requested_gt0"),
        ),
        migrations.AddConstraint(
            model_name="customerallocation",
            constraint=models.CheckConstraint(condition=models.Q(amount__gt=0), name="allocation_amount_gt0"),
        ),
        migrations.AddConstraint(
            model_name="customerallocation",
            constraint=models.CheckConstraint(condition=models.Q(credit_amount__gte=0), name="allocation_credit_gte0"),
        ),
    ]
