from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("purchases", "0008_landed_cost_valuation_adjustments"),
        ("accounting", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="LandedCostReversal",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("reversal_date", models.DateField()),
                ("reason", models.CharField(max_length=500)),
                ("idempotency_key", models.CharField(max_length=128, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("cost_document", models.OneToOneField(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="reversal",
                    to="purchases.landedcostdocument",
                )),
                ("created_by", models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name="landed_cost_reversals_created",
                    to=settings.AUTH_USER_MODEL,
                )),
                ("journal_entry", models.OneToOneField(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="landed_cost_source_reversal",
                    to="accounting.journalentry",
                )),
            ],
            options={"ordering": ["reversal_date", "id"]},
        ),
        migrations.CreateModel(
            name="LandedCostReversalAdjustment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("journal_entry", models.OneToOneField(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="landed_cost_adjustment_reversal",
                    to="accounting.journalentry",
                )),
                ("original_adjustment", models.OneToOneField(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="reversal_record",
                    to="purchases.landedcostvaluationadjustment",
                )),
                ("reversal", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="adjustment_reversals",
                    to="purchases.landedcostreversal",
                )),
            ],
            options={"ordering": ["id"]},
        ),
    ]
