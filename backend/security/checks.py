"""Database catalog drift check (§15.1) — registry vs security.Permission.

The registry module ``security.permissions_catalog`` is the single source of
truth. This check asserts that the seeded ``security.Permission`` rows still
match it exactly and fails loudly on any drift, so the database catalog can
never silently become an independent source of authorization truth (§15.1).

Registered with ``Tags.database`` so Django runs it only when database
access is meaningful: during ``migrate`` (per database) and via
``manage.py check --database <alias>``. A database whose
``security_permission`` table does not exist yet (fresh, pre-migration) is
skipped — that is unmigrated state, not catalog drift.
"""
from django.core import checks
from django.core.checks import Tags, register

from security.permissions_catalog import (
    CATALOG_BY_KEY,
    PermissionCatalogError,
    validate_catalog,
)

CATALOG_DRIFT_CHECK_ID = "security.E001"
CATALOG_INVALID_CHECK_ID = "security.E002"

_COMPARED_FIELDS = ("domain", "resource", "action", "description", "is_sensitive")


def _registry_errors():
    try:
        validate_catalog()
    except PermissionCatalogError as exc:
        return [
            checks.Error(
                f"W0-2A permission catalog registry is invalid and must never "
                f"be used as an authorization source until corrected: {exc}",
                id=CATALOG_INVALID_CHECK_ID,
            )
        ]
    return []


def _catalog_table_exists(alias):
    from django.db import connections

    connection = connections[alias]
    table_names = set(connection.introspection.table_names())
    from security.models import Permission

    return Permission._meta.db_table in table_names


def _drift_errors_for_alias(alias):
    from django.db import router
    from security.models import Permission

    if not router.allow_migrate_model(alias, Permission):
        return []
    if not _catalog_table_exists(alias):
        return []

    db_rows = {
        row["key"]: row
        for row in Permission.objects.using(alias).values(
            "key", *_COMPARED_FIELDS
        )
    }
    errors = []
    db_keys = set(db_rows)
    registry_keys = set(CATALOG_BY_KEY)

    missing = sorted(registry_keys - db_keys)
    extra = sorted(db_keys - registry_keys)
    if missing:
        errors.append(
            checks.Error(
                f"Catalog drift on database alias {alias!r}: {len(missing)} "
                f"registered permission keys are missing from "
                f"security.Permission (first few: {missing[:5]}). The seeded "
                f"catalog must match SECURITY_PERMISSION_CATALOG exactly "
                f"(§15.1). Re-run the RBAC seed or reconcile manually; do not "
                f"edit the registry to match the database.",
                id=CATALOG_DRIFT_CHECK_ID,
            )
        )
    if extra:
        errors.append(
            checks.Error(
                f"Catalog drift on database alias {alias!r}: {len(extra)} "
                f"unregistered keys exist in security.Permission (first few: "
                f"{extra[:5]}). Invented keys are prohibited (§15.1); remove "
                f"or register them through an approved batch.",
                id=CATALOG_DRIFT_CHECK_ID,
            )
        )
    changed = []
    for key in sorted(registry_keys & db_keys):
        entry = CATALOG_BY_KEY[key]
        row = db_rows[key]
        for field in _COMPARED_FIELDS:
            if row[field] != entry[field]:
                changed.append(f"{key}.{field}: db={row[field]!r} registry={entry[field]!r}")
    if changed:
        errors.append(
            checks.Error(
                f"Catalog drift on database alias {alias!r}: "
                f"{len(changed)} catalog metadata mismatches between "
                f"security.Permission and SECURITY_PERMISSION_CATALOG "
                f"(first few: {changed[:5]}). The database catalog must not "
                f"become an independent source of authorization truth (§15.1).",
                id=CATALOG_DRIFT_CHECK_ID,
            )
        )
    return errors


def check_permission_catalog_sync_for_alias(alias):
    """Run the registry + drift check for one database alias.

    Exposed for direct, deterministic use by the test suite (the tagged
    Django check is only invoked by migrate / check --database).
    """
    errors = _registry_errors()
    if errors:
        # A broken registry must never be compared against the database; the
        # registry error alone is fatal and reported as-is.
        return errors
    return _drift_errors_for_alias(alias)


@register(Tags.database)
def check_permission_catalog_sync(app_configs=None, **kwargs):
    errors = _registry_errors()
    if errors:
        return errors
    for alias in kwargs.get("databases") or []:
        errors.extend(_drift_errors_for_alias(alias))
    return errors
