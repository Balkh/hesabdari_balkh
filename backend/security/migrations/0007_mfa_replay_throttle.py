from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("security", "0006_mfa_session_registry")]

    operations = [
        migrations.AddField(
            model_name="securitymfadevice",
            name="last_accepted_counter",
            field=models.BigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="securitymfadevice",
            name="failed_attempts",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="securitymfadevice",
            name="locked_until",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
