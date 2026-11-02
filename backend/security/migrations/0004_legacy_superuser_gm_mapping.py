"""W0-2A / R1 — legacy superuser compatibility mapping (§24.2).

Disposition: "Superuser→GM mapping | MIGRATION (0004; idempotent; no-op on
current DBs)". This is the exact, narrowly scoped rule approved by the
architecture; it is deliberately NOT a general privilege policy:

- It creates an active, indefinite GM ``UserRoleAssignment`` for every
  existing ``User`` with ``is_superuser=True`` so that standing Django
  superusers are not silently degraded when RBAC enforcement is wired in a
  later batch. ``granted_by`` is NULL (system/migration attribution per
  §14.1) and ``reason`` carries the marker constant below for auditability.
- An assignment whose live slot is already occupied (revoked_at IS NULL) is
  never duplicated: the idempotency guard is the §14.4 partial unique plus
  an explicit existence check.
- Inactive superusers also receive the assignment: while the account is
  inactive the assignment is inert (the resolver denies inactive accounts
  before any grant lookup, §16.1 step 2). No extra policy condition is
  invented here.
- ``is_superuser`` alone STILL confers no ERP authorization (§5.1): this
  migration only backfills role rows; it does not touch passwords,
  authentication, active status, or is_staff, and it never assigns
  non-superusers.

Reverse policy: the reverse deletes exactly the rows this migration
created — GM assignments with ``granted_by IS NULL`` and the exact marker
reason on superuser accounts — leaving operator-created assignments
untouched.
"""
from django.db import migrations
from django.utils import timezone


SUPERUSER_GM_REASON = (
    "W0-2A migration 0004: legacy superuser compatibility mapping (§24.2)"
)


def assign_gm_to_legacy_superusers(apps, schema_editor):
    User = apps.get_model("auth", "User")
    Role = apps.get_model("security", "Role")
    UserRoleAssignment = apps.get_model("security", "UserRoleAssignment")

    gm_role = Role.objects.filter(code="GM").first()
    if gm_role is None:
        raise RuntimeError(
            "security.Role 'GM' is missing; migration 0004 requires the "
            "canonical role seed (0003). Apply migrations in order."
        )

    now = timezone.now()
    for user in User.objects.filter(is_superuser=True).order_by("pk"):
        has_live_assignment = (
            UserRoleAssignment.objects.filter(
                user=user, role=gm_role, revoked_at__isnull=True
            ).exists()
        )
        if has_live_assignment:
            continue
        UserRoleAssignment.objects.create(
            user=user,
            role=gm_role,
            start_at=now,
            end_at=None,
            reason=SUPERUSER_GM_REASON,
            granted_by=None,
        )


def remove_migration_created_superuser_gm_assignments(apps, schema_editor):
    User = apps.get_model("auth", "User")
    Role = apps.get_model("security", "Role")
    UserRoleAssignment = apps.get_model("security", "UserRoleAssignment")

    gm_role = Role.objects.filter(code="GM").first()
    if gm_role is None:
        return
    UserRoleAssignment.objects.filter(
        user__is_superuser=True,
        role=gm_role,
        granted_by__isnull=True,
        reason=SUPERUSER_GM_REASON,
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("security", "0003_seed_rbac_catalog"),
    ]

    operations = [
        migrations.RunPython(
            assign_gm_to_legacy_superusers,
            reverse_code=remove_migration_created_superuser_gm_assignments,
        ),
    ]
