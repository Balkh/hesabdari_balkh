from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL), ("goods_in_transit", "0001_initial"), ("sales", "0003_saleline_transit_lot")]
    operations = [
        migrations.AddField(model_name="transitreceipt", name="company_quantity", field=models.PositiveIntegerField(default=0)),
        migrations.AddField(model_name="transitreceipt", name="customer_custody_quantity", field=models.PositiveIntegerField(default=0)),
        migrations.AlterField(model_name="transitreceipt", name="stock_movement", field=models.OneToOneField(null=True, blank=True, on_delete=django.db.models.deletion.PROTECT, related_name="transit_receipt", to="inventory.stockmovement")),
        migrations.AlterField(model_name="transitreceipt", name="journal_entry", field=models.OneToOneField(null=True, blank=True, on_delete=django.db.models.deletion.PROTECT, related_name="transit_receipt", to="accounting.journalentry")),
        migrations.CreateModel(name="TransitCustomerCustody", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("quantity", models.PositiveIntegerField()), ("receipt_date", models.DateField()), ("created_at", models.DateTimeField(auto_now_add=True)),
            ("customer", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="transit_customer_custody", to="parties.party")),
            ("receipt", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="customer_custody_rows", to="goods_in_transit.transitreceipt")),
            ("sale_line", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="transit_customer_custody", to="sales.saleline")),
            ("warehouse", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="transit_customer_custody", to="warehouses.warehouse")),
        ], options={"ordering":["receipt_date","id"]}),
        migrations.CreateModel(name="TransitDestinationTransfer", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("quantity", models.PositiveIntegerField()), ("transfer_date", models.DateField()), ("idempotency_key", models.CharField(max_length=128, unique=True)), ("created_at", models.DateTimeField(auto_now_add=True)),
            ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="transit_destination_transfers_created", to=settings.AUTH_USER_MODEL)),
            ("from_warehouse", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="transit_destination_transfers_from", to="warehouses.warehouse")),
            ("lot", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="destination_transfers", to="goods_in_transit.goodsintransitlot")),
            ("to_warehouse", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="transit_destination_transfers_to", to="warehouses.warehouse")),
        ], options={"ordering":["transfer_date","id"]}),
        migrations.AddConstraint(model_name="transitcustomercustody", constraint=models.CheckConstraint(condition=models.Q(quantity__gt=0), name="transit_customer_custody_qty_gt0")),
        migrations.AddConstraint(model_name="transitcustomercustody", constraint=models.UniqueConstraint(fields=("receipt","sale_line"), name="uniq_transit_receipt_sale_line_custody")),
        migrations.AddConstraint(model_name="transitdestinationtransfer", constraint=models.CheckConstraint(condition=models.Q(quantity__gt=0), name="transit_destination_transfer_qty_gt0")),
    ]
