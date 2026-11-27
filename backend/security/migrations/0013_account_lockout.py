# W0-2D durable account lockout state and privacy-preserving authentication history.
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [
        ("security", "0012_emergency_owner_key"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="SecurityAccountLockout",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("failed_password_attempts", models.PositiveSmallIntegerField(default=0)),
                ("last_failed_at", models.DateTimeField(blank=True, null=True)),
                ("locked_until", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="security_account_lockout", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "constraints": [
                    models.CheckConstraint(condition=models.Q(failed_password_attempts__lte=5), name="sec_lock_failures_at_most_5"),
                ],
                "indexes": [
                    models.Index(fields=["locked_until"], name="sec_lock_locked_until_idx"),
                ],
            },
        ),
        migrations.CreateModel(
            name="SecurityLoginAttempt",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("username_digest", models.CharField(max_length=64)),
                ("source_digest", models.CharField(max_length=64)),
                ("outcome", models.CharField(choices=[("PASSWORD_FAILED", "Password failed"), ("MFA_FAILED", "MFA failed"), ("LOCKED", "Account locked"), ("SUCCESS", "Successful login")], max_length=20)),
                ("occurred_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("user", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="security_login_attempts", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["-occurred_at", "-id"],
                "indexes": [
                    models.Index(fields=["user", "occurred_at"], name="sec_login_user_time_idx"),
                    models.Index(fields=["username_digest", "source_digest", "occurred_at"], name="sec_login_name_src_time"),
                    models.Index(fields=["source_digest", "occurred_at"], name="sec_login_source_time"),
                ],
            },
        ),
    ]
