# Generated for the purchase-wide transit completion gate.
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("goods_in_transit", "0005_transit_loss_snapshot_constraints"),
        ("purchases", "0009_landed_cost_reversals"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(
            name="TransitPurchaseCompletion",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("completion_date", models.DateField()),
                ("reason", models.TextField()),
                ("idempotency_key", models.CharField(max_length=128, unique=True)),
                ("completed_at", models.DateTimeField(auto_now_add=True)),
                ("completed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="transit_purchases_completed", to=settings.AUTH_USER_MODEL)),
                ("purchase", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="transit_completion", to="purchases.purchase")),
            ],
            options={"ordering": ["completion_date", "id"]},
        ),
    ]
