from django.db import migrations, models
from django.db.models import F, Q


class Migration(migrations.Migration):
    dependencies = [("security", "0010_employee_mfa_requirement")]

    operations = [
        migrations.CreateModel(
            name="SecurityBootstrapToken",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("purpose", models.CharField(choices=[("INITIAL_GM", "Initial GM bootstrap")], default="INITIAL_GM", max_length=24)),
                ("token_hash", models.CharField(max_length=64, unique=True)),
                ("issued_at", models.DateTimeField()),
                ("expires_at", models.DateTimeField()),
                ("consumed_at", models.DateTimeField(blank=True, null=True)),
                ("revoked_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={
                "constraints": [
                    models.CheckConstraint(condition=Q(expires_at__gt=F("issued_at")), name="security_bootstrap_expiry_after_issue"),
                    models.CheckConstraint(condition=Q(consumed_at__isnull=True) | Q(revoked_at__isnull=True), name="security_bootstrap_one_terminal_state"),
                    models.UniqueConstraint(fields=("purpose",), condition=Q(consumed_at__isnull=True, revoked_at__isnull=True), name="security_bootstrap_one_live_token"),
                ],
                "indexes": [models.Index(fields=["purpose", "expires_at"], name="sec_boot_purpose_exp_idx")],
            },
        ),
    ]
