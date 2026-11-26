# Extend the audit action choices for W0-2D security events.
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("security", "0013_account_lockout"),
    ]

    operations = [
        migrations.AlterField(
            model_name="auditevent",
            name="action",
            field=models.CharField(
                choices=[
                    ("LOGIN", "Login"),
                    ("LOGOUT", "Logout"),
                    ("CREATE", "Create"),
                    ("UPDATE", "Update"),
                    ("POST", "Post"),
                    ("REVERSE", "Reverse"),
                    ("APPROVE", "Approve"),
                    ("LOGIN_FAILED", "Failed login"),
                    ("ACCOUNT_LOCKED", "Account locked"),
                    ("ACCOUNT_UNLOCKED", "Account unlocked"),
                ],
                max_length=20,
            ),
        ),
    ]
