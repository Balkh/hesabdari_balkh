"""W0-2A / R1 — seed the RBAC permission catalog and canonical roles.

§24.2 disposition: "Permission catalog registry + seed | SCHEMA+SEED (0003;
162 keys / 20 domains)". Content comes exclusively from
``security.permissions_catalog.SECURITY_PERMISSION_CATALOG``; the seed is
deterministic and idempotent (``security.seed.seed_rbac_catalog``).

Reverse policy: the reverse operation is intentionally a NO-OP. Catalog
rows are never deleted (§14.8 — deactivated instead), and a reverse that
deleted seeded roles would violate the M4/M3 deletion policies on any
database where user assignments exist. Rolling back to 0002 therefore
leaves the reference rows in place; re-applying 0003 converges to the same
state because the seed is idempotent. This is documented in
docs/operations/RBAC_FOUNDATION.md and the owner handoff report.
"""
import security.seed
from django.db import migrations


def seed_catalog(apps, schema_editor):
    Role = apps.get_model("security", "Role")
    Permission = apps.get_model("security", "Permission")
    RolePermission = apps.get_model("security", "RolePermission")
    security.seed.seed_rbac_catalog(
        role_model=Role,
        permission_model=Permission,
        role_permission_model=RolePermission,
    )


class Migration(migrations.Migration):

    dependencies = [
        ("security", "0002_rbac_models"),
    ]

    operations = [
        migrations.RunPython(seed_catalog, reverse_code=migrations.RunPython.noop),
    ]
