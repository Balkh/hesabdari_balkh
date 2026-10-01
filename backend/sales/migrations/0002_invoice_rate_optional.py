from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [("sales", "0001_initial")]
    operations = [
        migrations.AlterField(
            model_name="sale",
            name="exchange_rate",
            field=models.DecimalField(blank=True, decimal_places=4, max_digits=20, null=True),
        ),
        migrations.AlterField(
            model_name="sale",
            name="rate_date",
            field=models.DateField(blank=True, null=True),
        ),
    ]
