from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("goods_in_transit", "0002_custody_destination_transfer"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="TransitLossEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("quantity", models.PositiveIntegerField()),
                ("loss_date", models.DateField()),
                ("reason", models.TextField()),
                ("idempotency_key", models.CharField(max_length=128, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="transit_loss_events_created", to=settings.AUTH_USER_MODEL)),
                ("lot", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="loss_events", to="goods_in_transit.goodsintransitlot")),
            ],
            options={"ordering": ["loss_date", "id"]},
        ),
        migrations.AddConstraint(
            model_name="transitlossevent",
            constraint=models.CheckConstraint(condition=models.Q(quantity__gt=0), name="transit_loss_qty_gt0"),
        ),
    ]
