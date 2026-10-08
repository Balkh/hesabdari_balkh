from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("accounting", "0008_cross_currency_clearing_account"),
        ("goods_in_transit", "0001_initial"),
        ("sales", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="TransitSaleAllocation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("quantity", models.PositiveIntegerField()),
                ("unit_cost", models.DecimalField(decimal_places=4, max_digits=20)),
                ("idempotency_key", models.CharField(max_length=128, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("cogs_journal", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="transit_sale_allocation", to="accounting.journalentry")),
                ("sale_line", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="transit_allocation", to="sales.saleline")),
                ("transit_lot", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="sale_allocations", to="goods_in_transit.goodsintransitlot")),
            ],
            options={"ordering": ["id"]},
        ),
        migrations.AddConstraint(
            model_name="transitsaleallocation",
            constraint=models.CheckConstraint(condition=models.Q(quantity__gt=0), name="transit_sale_alloc_qty_gt0"),
        ),
        migrations.AddConstraint(
            model_name="transitsaleallocation",
            constraint=models.CheckConstraint(condition=models.Q(unit_cost__gte=0), name="transit_sale_alloc_cost_gte0"),
        ),
    ]
