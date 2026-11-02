"""Canonical RBAC seed service (§15.1) — deterministic and idempotent.

Seeds, in order:
1. The 162 catalog rows from ``SECURITY_PERMISSION_CATALOG`` (M2).
2. The three canonical system roles GM / ACCOUNTANT / WAREHOUSE_KEEPER (M1).
3. The approved role-permission matrices (M3): GM 152 / Accountant 102 /
   Warehouse Keeper 12.

Idempotency and non-interference rules:
- ``get_or_create`` only: repeated execution never duplicates rows and never
  overwrites operator-managed rows (a deactivated or edited row is left
  exactly as found; resulting registry/DB divergence is caught loudly by
  the catalog drift check, not silently rewritten here).
- UNRESOLVED and RESERVED keys are registered for stability but granted to
  no role (§15.1); they are never converted into usable grants.
- No user-role assignment is ever created here: seeding grants roles and
  permissions as reference data only. User attribution belongs to the
  migration-level legacy-superuser mapping (0004) and to future W0-2B
  administration services, never to this seeder.

The service takes the model classes as parameters so the data migration can
pass historical models while tests pass the live models.
"""
from security.permissions_catalog import (
    ROLE_SEEDS,
    SECURITY_PERMISSION_CATALOG,
    validate_catalog,
)


def seed_rbac_catalog(*, role_model, permission_model, role_permission_model):
    """Seed the RBAC reference data. Returns a summary dict for evidence.

    Raises ``PermissionCatalogError`` if the registry itself is invalid —
    the migration data assertion (§15.1) and every caller rely on this to
    refuse seeding a broken catalog.
    """
    validate_catalog()

    permissions_by_key = {}
    for entry in SECURITY_PERMISSION_CATALOG:
        permission, _created = permission_model.objects.get_or_create(
            key=entry["key"],
            defaults={
                "domain": entry["domain"],
                "resource": entry["resource"],
                "action": entry["action"],
                "description": entry["description"],
                "is_sensitive": entry["is_sensitive"],
                "is_active": True,
            },
        )
        permissions_by_key[entry["key"]] = permission

    roles_by_code = {}
    for code, name, name_fa, description, _seed_keys in ROLE_SEEDS:
        role, _created = role_model.objects.get_or_create(
            code=code,
            defaults={
                "name": name,
                "name_fa": name_fa,
                "description": description,
                "is_active": True,
                "is_system": True,
            },
        )
        roles_by_code[code] = role

    role_permissions_created = 0
    for code, _name, _name_fa, _description, seed_keys in ROLE_SEEDS:
        for key in seed_keys:
            _link, created = role_permission_model.objects.get_or_create(
                role=roles_by_code[code],
                permission=permissions_by_key[key],
                defaults={"granted_by": None},
            )
            if created:
                role_permissions_created += 1

    return {
        "permissions_total": len(permissions_by_key),
        "roles_total": len(roles_by_code),
        "role_permissions_created": role_permissions_created,
        "role_permission_targets": {
            code: len(seed_keys)
            for code, _n, _nf, _d, seed_keys in ROLE_SEEDS
        },
    }
