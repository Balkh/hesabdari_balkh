# Generated manually because the implementation environment has no installed Django executable.

import django.db.models.deletion
from decimal import Decimal
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = [
        ("currencies", "0001_initial"),
        ("parties", "0001_initial"),
        ("products", "0001_initial"),
        ("uom", "0001_initial"),
        ("warehouses", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Sale",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("document_number", models.CharField(max_length=30, unique=True)),
                ("sale_date", models.DateField()),
                ("exchange_rate", models.DecimalField(decimal_places=4, max_digits=20)),
                ("rate_date", models.DateField()),
                ("sale_type", models.CharField(choices=[("AVAILABLE", "Available"), ("FUTURE", "Future")], max_length=10)),
                ("subtotal", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=20)),
                ("total_discount", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=20)),
                ("total", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=20)),
                ("status", models.CharField(choices=[("DRAFT", "Draft"), ("FINALIZED", "Finalized")], default="DRAFT", max_length=10)),
                ("finalized_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="sales_created", to=settings.AUTH_USER_MODEL)),
                ("currency", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="sales", to="currencies.currency")),
                ("customer", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="sales", to="parties.party")),
            ],
            options={"ordering": ["sale_date", "document_number"]},
        ),
        migrations.CreateModel(
            name="SaleLine",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("quantity", models.IntegerField()),
                ("unit_price", models.DecimalField(decimal_places=4, max_digits=20)),
                ("discount", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=20)),
                ("line_total", models.DecimalField(decimal_places=2, max_digits=20)),
                ("net_total", models.DecimalField(decimal_places=2, max_digits=20)),
                ("product", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="sale_lines", to="products.product")),
                ("sale", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="lines", to="sales.sale")),
                ("unit", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="sale_lines", to="uom.unitofmeasure")),
                ("warehouse", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="sale_lines", to="warehouses.warehouse")),
            ],
            options={"ordering": ["id"]},
        ),
        migrations.AddConstraint(model_name="saleline", constraint=models.CheckConstraint(condition=models.Q(quantity__gt=0), name="sale_line_qty_gt0")),
        migrations.AddConstraint(model_name="saleline", constraint=models.CheckConstraint(condition=models.Q(unit_price__gte=0), name="sale_line_price_gte0")),
        migrations.AddConstraint(model_name="saleline", constraint=models.CheckConstraint(condition=models.Q(discount__gte=0), name="sale_line_discount_gte0")),
        migrations.AddConstraint(model_name="saleline", constraint=models.CheckConstraint(condition=models.Q(line_total__gte=0), name="sale_line_total_gte0")),
        migrations.AddConstraint(model_name="saleline", constraint=models.CheckConstraint(condition=models.Q(net_total__gte=0), name="sale_line_net_gte0")),
    ]
