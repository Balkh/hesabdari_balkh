# Align the historical constraint state with the current model definition.
from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies = [
        ("security", "0007_mfa_replay_throttle"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="securitymfadevice",
            name="security_mfa_status_confirmation_consistent",
        ),
        migrations.AddConstraint(
            model_name="securitymfadevice",
            constraint=models.CheckConstraint(
                condition=(
                    Q(status="PENDING", confirmed_at__isnull=True)
                    | Q(status="ACTIVE", confirmed_at__isnull=False)
                    | Q(status="DISABLED")
                ),
                name="security_mfa_status_confirmation_consistent",
            ),
        ),
    ]
