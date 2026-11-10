from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies = [("security", "0008_rebuild_mfa_status_confirmation_constraint")]

    operations = [
        migrations.AddField(
            model_name="securityloginsession",
            name="slot_number",
            field=models.PositiveSmallIntegerField(default=1),
        ),
        migrations.AddConstraint(
            model_name="securityloginsession",
            constraint=models.CheckConstraint(
                condition=Q(slot_number__in=(1, 2)),
                name="security_session_slot_1_2",
            ),
        ),
        migrations.AddConstraint(
            model_name="securityloginsession",
            constraint=models.UniqueConstraint(
                fields=("user", "slot_number"),
                condition=Q(revoked_at__isnull=True),
                name="sec_sess_usr_live_slot",
            ),
        ),
    ]
