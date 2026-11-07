# W0-2C durable MFA credentials and session registry.
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.db.models import F, Q


class Migration(migrations.Migration):
    dependencies = [
        ("security", "0005_gmroleslot"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="SecurityMFADevice",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("status", models.CharField(choices=[("PENDING", "Pending enrollment"), ("ACTIVE", "Active"), ("DISABLED", "Disabled")], default="PENDING", max_length=10)),
                ("secret_format_version", models.PositiveSmallIntegerField(default=1)),
                ("secret_key_id", models.CharField(max_length=100)),
                ("secret_nonce", models.BinaryField(max_length=12)),
                ("secret_ciphertext", models.BinaryField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("confirmed_at", models.DateTimeField(blank=True, null=True)),
                ("disabled_at", models.DateTimeField(blank=True, null=True)),
                ("last_used_at", models.DateTimeField(blank=True, null=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="security_mfa_devices", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(condition=Q(("status", "ACTIVE")), fields=("user",), name="security_mfa_one_active_device"),
                    models.CheckConstraint(condition=Q(("secret_format_version", 1)), name="security_mfa_secret_version_v1"),
                    models.CheckConstraint(condition=Q(("status", "PENDING"), ("confirmed_at__isnull", True)) | Q(("status", "ACTIVE"), ("confirmed_at__isnull", False)) | Q(("status", "DISABLED")), name="security_mfa_status_confirmation_consistent"),
                ],
                "indexes": [models.Index(fields=["user", "status"], name="security_mfa_user_status_idx")],
            },
        ),
        migrations.CreateModel(
            name="SecurityRecoveryCode",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code_hash", models.CharField(max_length=256)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("used_at", models.DateTimeField(blank=True, null=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="security_recovery_codes", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "constraints": [models.UniqueConstraint(fields=("user", "code_hash"), name="security_recovery_user_hash_unique")],
                "indexes": [models.Index(fields=["user", "used_at"], name="security_recovery_user_used_idx")],
            },
        ),
        migrations.CreateModel(
            name="SecurityLoginSession",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("session_key_hash", models.CharField(max_length=64, unique=True)),
                ("created_at", models.DateTimeField()),
                ("last_seen_at", models.DateTimeField()),
                ("idle_expires_at", models.DateTimeField()),
                ("absolute_expires_at", models.DateTimeField()),
                ("revoked_at", models.DateTimeField(blank=True, null=True)),
                ("revoke_reason", models.CharField(blank=True, default="", max_length=40)),
                ("mfa_verified_at", models.DateTimeField(blank=True, null=True)),
                ("user_agent_digest", models.CharField(blank=True, default="", max_length=64)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="security_login_sessions", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "constraints": [
                    models.CheckConstraint(condition=Q(("absolute_expires_at__gt", F("created_at"))), name="security_session_absolute_after_created"),
                    models.CheckConstraint(condition=Q(("idle_expires_at__lte", F("absolute_expires_at"))), name="security_session_idle_before_absolute"),
                ],
                "indexes": [models.Index(fields=["user", "revoked_at", "idle_expires_at"], name="sec_sess_usr_active_idx")],
            },
        ),
    ]
