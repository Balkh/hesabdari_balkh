from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True
    dependencies = [
        ("accounting", "0007_fx_settlement_record"),
        ("currencies", "0001_initial"),
        ("parties", "0001_initial"),
    ]
    operations = [
        migrations.CreateModel(
            name="Payment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("document_number", models.CharField(max_length=30, unique=True)),
                ("payment_date", models.DateField()),
                ("amount", models.DecimalField(decimal_places=2, max_digits=20)),
                ("purpose", models.CharField(choices=[("RECEIVABLE", "Customer Receivable"), ("CUSTOMER_CREDIT", "Customer Credit / Advance")], max_length=20)),
                ("description", models.CharField(blank=True, default="", max_length=500)),
                ("reference", models.CharField(blank=True, default="", max_length=200)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("currency", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="payments", to="currencies.currency")),
                ("journal_entry", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="payment_document", to="accounting.journalentry")),
                ("party", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="payments", to="parties.party")),
            ],
            options={"ordering": ["payment_date", "document_number"]},
        ),
    ]
