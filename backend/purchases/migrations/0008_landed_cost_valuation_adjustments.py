from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("purchases", "0007_landed_cost_documents"),
        ("inventory", "0001_initial"),
        ("accounting", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="LandedCostValuationAdjustment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("source_reference", models.CharField(max_length=200)),
                ("adjustment_type", models.CharField(max_length=40)),
                ("amount_afn", models.DecimalField(decimal_places=2, max_digits=20)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("cost_document", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="valuation_adjustments", to="purchases.landedcostdocument")),
                ("journal_entry", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="landed_cost_valuation_adjustment", to="accounting.journalentry")),
                ("movement", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="landed_cost_valuation_adjustments", to="inventory.stockmovement")),
            ],
            options={"ordering": ["cost_document_id", "id"]},
        ),
        migrations.AddConstraint(
            model_name="landedcostvaluationadjustment",
            constraint=models.CheckConstraint(condition=models.Q(("amount_afn__gt", 0)), name="landed_cost_adjustment_afn_gt0"),
        ),
        migrations.AddConstraint(
            model_name="landedcostvaluationadjustment",
            constraint=models.UniqueConstraint(fields=("cost_document", "source_reference", "adjustment_type"), name="uniq_lc_valuation_adjustment_ref"),
        ),
    ]
