from django.conf import settings
from django.db import migrations, models
from django.db.models import Q
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("security", "0011_security_bootstrap_token"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="SecurityEmergencyOwnerKey",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("scope", models.CharField(choices=[("GM_RECOVERY", "GM emergency recovery")], default="GM_RECOVERY", max_length=24)),
                ("source", models.CharField(choices=[("INITIAL_BOOTSTRAP", "Initial GM bootstrap"), ("ROTATION", "Local key rotation"), ("EMERGENCY_RECOVERY", "Offline GM emergency recovery")], max_length=32)),
                ("key_hash", models.CharField(max_length=64, unique=True)),
                ("issued_at", models.DateTimeField()),
                ("consumed_at", models.DateTimeField(blank=True, null=True)),
                ("revoked_at", models.DateTimeField(blank=True, null=True)),
                ("revoke_reason", models.CharField(blank=True, default="", max_length=40)),
                ("consumed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="emergency_owner_keys_consumed", to=settings.AUTH_USER_MODEL)),
                ("issued_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="emergency_owner_keys_issued", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "constraints": [
                    models.CheckConstraint(condition=Q(scope="GM_RECOVERY"), name="sec_em_owner_gm_scope_only"),
                    models.CheckConstraint(condition=Q(consumed_at__isnull=True, consumed_by__isnull=True) | Q(consumed_at__isnull=False, consumed_by__isnull=False), name="sec_em_owner_consumed_actor"),
                    models.CheckConstraint(condition=Q(consumed_at__isnull=True) | Q(revoked_at__isnull=True), name="sec_em_owner_one_terminal"),
                    models.UniqueConstraint(fields=("scope",), condition=Q(consumed_at__isnull=True, revoked_at__isnull=True), name="sec_em_owner_one_live"),
                ],
                "indexes": [models.Index(fields=["scope", "consumed_at", "revoked_at"], name="sec_em_owner_status_idx")],
            },
        ),
    ]
