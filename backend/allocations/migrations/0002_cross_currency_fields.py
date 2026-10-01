from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    dependencies = [
        ("allocations", "0001_initial"),
        ("payments", "0002_cross_currency_settlement"),
    ]
    operations = [
        migrations.AddField(
            model_name="customerallocation",
            name="settlement",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="allocations", to="payments.crosscurrencysettlement"),
        ),
        migrations.AddField(
            model_name="customerallocation",
            name="payment_amount",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=20),
        ),
        migrations.AddConstraint(
            model_name="customerallocation",
            constraint=models.CheckConstraint(condition=models.Q(payment_amount__gte=0), name="allocation_payment_amount_gte0"),
        ),
    ]
