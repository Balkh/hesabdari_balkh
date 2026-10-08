from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("goods_in_transit", "0001_initial"),
        ("sales", "0002_transit_sale_allocation"),
    ]

    operations = [
        migrations.AddField(
            model_name="saleline",
            name="transit_lot",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="sale_lines",
                to="goods_in_transit.goodsintransitlot",
            ),
        ),
    ]
