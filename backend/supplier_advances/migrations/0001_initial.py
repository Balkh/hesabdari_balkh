from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("accounting", "0008_cross_currency_clearing_account"),
        ("currencies", "0001_initial"),
        ("parties", "0001_initial"),
        ("purchases", "0001_initial"),
    ]
    operations = [
        migrations.CreateModel(
            name="SupplierAdvance",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("document_number", models.CharField(max_length=30, unique=True)),
                ("advance_date", models.DateField()),
                ("amount", models.DecimalField(decimal_places=2, max_digits=20)),
                ("status", models.CharField(choices=[("POSTED", "Posted"), ("REVERSED", "Reversed")], default="POSTED", max_length=10)),
                ("description", models.CharField(blank=True, default="", max_length=500)),
                ("reference", models.CharField(blank=True, default="", max_length=200)),
                ("idempotency_key", models.CharField(max_length=128, unique=True)),
                ("posted_at", models.DateTimeField(auto_now_add=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="supplier_advances_created", to=settings.AUTH_USER_MODEL)),
                ("currency", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="supplier_advances", to="currencies.currency")),
                ("journal_entry", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="supplier_advance_document", to="accounting.journalentry")),
                ("supplier", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="supplier_advances", to="parties.party")),
            ],
            options={"ordering": ["advance_date", "document_number"]},
        ),
        migrations.CreateModel(
            name="SupplierAdvanceAllocation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("amount", models.DecimalField(decimal_places=2, max_digits=20)),
                ("idempotency_key", models.CharField(max_length=128, unique=True)),
                ("allocated_at", models.DateTimeField(auto_now_add=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="supplier_advance_allocations_created", to=settings.AUTH_USER_MODEL)),
                ("advance", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="allocations", to="supplier_advances.supplieradvance")),
                ("journal_entry", models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="supplier_advance_allocation", to="accounting.journalentry")),
                ("purchase", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="supplier_advance_allocations", to="purchases.purchase")),
            ],
            options={"ordering": ["id"]},
        ),
        migrations.CreateModel(
            name="SupplierAdvanceAllocationReversal",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("reason", models.CharField(max_length=500)),
                ("idempotency_key", models.CharField(max_length=128, unique=True)),
                ("reversed_at", models.DateTimeField(auto_now_add=True)),
                ("allocation", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="reversal", to="supplier_advances.supplieradvanceallocation")),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="supplier_advance_allocation_reversals_created", to=settings.AUTH_USER_MODEL)),
                ("journal_entry", models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="supplier_advance_allocation_reversal", to="accounting.journalentry")),
            ],
            options={"ordering": ["id"]},
        ),
        migrations.AddConstraint(
            model_name="supplieradvance",
            constraint=models.CheckConstraint(condition=models.Q(amount__gt=0), name="supplier_advance_amount_gt0"),
        ),
        migrations.AddConstraint(
            model_name="supplieradvanceallocation",
            constraint=models.CheckConstraint(condition=models.Q(amount__gt=0), name="supplier_advance_alloc_amount_gt0"),
        ),
    ]
