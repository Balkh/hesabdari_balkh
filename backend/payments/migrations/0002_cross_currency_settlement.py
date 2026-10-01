from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    dependencies = [
        ("accounting", "0008_cross_currency_clearing_account"),
        ("payments", "0001_initial"),
    ]
    operations = [
        migrations.CreateModel(
            name="CrossCurrencySettlement",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("debt_amount", models.DecimalField(decimal_places=2, max_digits=20)),
                ("payment_amount", models.DecimalField(decimal_places=2, max_digits=20)),
                ("agreed_rate", models.DecimalField(decimal_places=8, max_digits=20)),
                ("rate_direction", models.CharField(max_length=80)),
                ("settled_at", models.DateTimeField()),
                ("status", models.CharField(choices=[("POSTED", "Posted"), ("REVERSED", "Reversed")], default="POSTED", max_length=10)),
                ("idempotency_key", models.CharField(max_length=128, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("cash_journal", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="cross_currency_cash_settlement", to="accounting.journalentry")),
                ("debt_currency", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="settlements_as_debt_currency", to="currencies.currency")),
                ("party", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="cross_currency_settlements", to="parties.party")),
                ("payment", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="cross_currency_settlement", to="payments.payment")),
                ("payment_currency", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="settlements_as_payment_currency", to="currencies.currency")),
                ("receivable_journal", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="cross_currency_receivable_settlement", to="accounting.journalentry")),
            ],
            options={
                "ordering": ["id"],
                "indexes": [models.Index(fields=["party", "debt_currency"], name="ccs_party_debt_cur_idx")],
                "constraints": [
                    models.CheckConstraint(condition=models.Q(debt_amount__gt=0), name="ccs_debt_amount_gt0"),
                    models.CheckConstraint(condition=models.Q(payment_amount__gt=0), name="ccs_payment_amount_gt0"),
                    models.CheckConstraint(condition=models.Q(agreed_rate__gt=0), name="ccs_rate_gt0"),
                ],
            },
        ),
    ]
