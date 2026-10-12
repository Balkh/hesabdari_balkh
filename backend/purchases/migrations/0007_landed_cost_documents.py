from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("purchases", "0006_landed_cost_weight_allocation"),
        ("parties", "0001_initial"),
        ("currencies", "0001_initial"),
        ("accounting", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="LandedCostDocument",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("document_number", models.CharField(max_length=30, unique=True)),
                ("cost_date", models.DateField()),
                ("amount", models.DecimalField(decimal_places=2, max_digits=20)),
                ("exchange_rate", models.DecimalField(decimal_places=4, max_digits=20)),
                ("rate_date", models.DateField()),
                ("afn_amount", models.DecimalField(decimal_places=2, max_digits=20)),
                ("category", models.CharField(max_length=40)),
                ("description", models.CharField(blank=True, default="", max_length=500)),
                ("status", models.CharField(choices=[("DRAFT", "Draft"), ("POSTED", "Posted")], default="DRAFT", max_length=10)),
                ("idempotency_key", models.CharField(max_length=128, unique=True)),
                ("posted_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="landed_cost_documents_created", to=settings.AUTH_USER_MODEL)),
                ("currency", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="landed_cost_documents", to="currencies.currency")),
                ("journal_entry", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="landed_cost_documents", to="accounting.journalentry")),
                ("payee", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="landed_cost_documents", to="parties.party")),
            ],
            options={"ordering": ["cost_date", "document_number"]},
        ),
        migrations.AddConstraint(
            model_name="landedcostdocument",
            constraint=models.CheckConstraint(condition=models.Q(("amount__gt", 0)), name="landed_cost_amount_gt0"),
        ),
        migrations.AddConstraint(
            model_name="landedcostdocument",
            constraint=models.CheckConstraint(condition=models.Q(("exchange_rate__gt", 0)), name="landed_cost_rate_gt0"),
        ),
        migrations.AddConstraint(
            model_name="landedcostdocument",
            constraint=models.CheckConstraint(condition=models.Q(("afn_amount__gt", 0)), name="landed_cost_afn_gt0"),
        ),
        migrations.AddConstraint(
            model_name="landedcostdocument",
            constraint=models.CheckConstraint(condition=~models.Q(("document_number", "")), name="landed_cost_doc_nonblank"),
        ),
        migrations.AddConstraint(
            model_name="landedcostdocument",
            constraint=models.CheckConstraint(condition=~models.Q(("category", "")), name="landed_cost_category_nonblank"),
        ),
        migrations.CreateModel(
            name="LandedCostAllocation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("method", models.CharField(choices=[("DIRECT", "Direct to purchase line"), ("WEIGHT", "Measured-weight allocation")], max_length=10)),
                ("amount", models.DecimalField(decimal_places=2, max_digits=20)),
                ("afn_amount", models.DecimalField(decimal_places=2, max_digits=20)),
                ("measured_weight_kg", models.DecimalField(blank=True, decimal_places=4, max_digits=20, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("cost_document", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="allocations", to="purchases.landedcostdocument")),
                ("purchase_line", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="landed_cost_allocations", to="purchases.purchaseline")),
            ],
            options={"ordering": ["cost_document_id", "id"]},
        ),
        migrations.AddConstraint(
            model_name="landedcostallocation",
            constraint=models.UniqueConstraint(fields=("cost_document", "purchase_line"), name="uniq_lc_doc_purchase_line"),
        ),
        migrations.AddConstraint(
            model_name="landedcostallocation",
            constraint=models.CheckConstraint(condition=models.Q(("amount__gt", 0)), name="landed_cost_alloc_amount_gt0"),
        ),
        migrations.AddConstraint(
            model_name="landedcostallocation",
            constraint=models.CheckConstraint(condition=models.Q(("afn_amount__gt", 0)), name="landed_cost_alloc_afn_gt0"),
        ),
        migrations.AddConstraint(
            model_name="landedcostallocation",
            constraint=models.CheckConstraint(condition=models.Q(("measured_weight_kg__isnull", True), ("measured_weight_kg__gt", 0), _connector="OR"), name="landed_cost_alloc_weight_gt0"),
        ),
    ]
