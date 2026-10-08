from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    dependencies = [("purchases", "0003_supplier_refund_settlement"), ("goods_in_transit", "0001_initial")]
    operations = [
        migrations.AlterField(model_name="purchasereturn", name="inventory_return", field=models.OneToOneField(null=True, blank=True, on_delete=django.db.models.deletion.PROTECT, related_name="purchase_financial_return", to="inventory.inventoryreturn")),
        migrations.AddField(model_name="purchasereturn", name="transit_lot", field=models.ForeignKey(null=True, blank=True, on_delete=django.db.models.deletion.PROTECT, related_name="purchase_returns", to="goods_in_transit.goodsintransitlot")),
        migrations.AlterField(model_name="purchasereturnreversal", name="stock_movement", field=models.OneToOneField(null=True, blank=True, on_delete=django.db.models.deletion.PROTECT, related_name="purchase_return_reversal", to="inventory.stockmovement")),
    ]
