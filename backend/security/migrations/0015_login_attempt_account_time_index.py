# Add an index for account-scoped login-failure throttling.
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("security", "0014_alter_auditevent_action"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="securityloginattempt",
            index=models.Index(
                fields=["username_digest", "occurred_at"],
                name="sec_login_name_time_idx",
            ),
        ),
    ]
