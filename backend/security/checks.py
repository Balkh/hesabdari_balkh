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



OPERATION_REGISTRY_CHECK_ID = "security.E003"
EXPECTED_PUBLIC_API_ROUTES = frozenset(
    {
        "api/v1/",
        "api/v1/health/",
        "api/v1/health/missing/",
        # Explicit authentication entry points: public by design, throttled,
        # CSRF-protected where state-changing, and never business endpoints.
        "api/v1/security/csrf/",
        "api/v1/security/auth/login/",
    }
)


def _public_route_allowlist_errors(public_routes):
    """Require the exact approved public API paths, not merely a matching count."""
    actual = set(public_routes)
    if (
        actual == EXPECTED_PUBLIC_API_ROUTES
        and len(public_routes) == len(EXPECTED_PUBLIC_API_ROUTES)
    ):
        return []
    unexpected = sorted(actual - EXPECTED_PUBLIC_API_ROUTES)
    missing = sorted(EXPECTED_PUBLIC_API_ROUTES - actual)
    return [
        checks.Error(
            "Public API allowlist mismatch: "
            f"unexpected={unexpected}, missing={missing}. "
            "Only the infrastructure probes plus the exact CSRF-cookie and password-login endpoints may use AllowAny.",
            id=OPERATION_REGISTRY_CHECK_ID,
        )
    ]


def _unclassified_api_callback_errors(route, view_class):
    """Reject API-namespace callbacks that are not inspectable DRF views.

    A normal Django callback has no DRF ``.cls`` metadata, so the operation
    registry cannot inspect its authentication/permission declarations.
    Treating that callback as outside the check would create an E003 blind
    spot under the protected API namespace.
    """
    if route.startswith("api/v1/") and view_class is None:
        return [
            checks.Error(
                f"API route {route!r} is not a DRF callback and cannot be "
                "verified by the ERP operation registry. Convert it to a "
                "DRF view with explicit permission declarations.",
                id=OPERATION_REGISTRY_CHECK_ID,
            )
        ]
    return []


@register()
def check_operation_registry(app_configs=None, **kwargs):
    """Validate that every protected first-party DRF operation is declared exactly once."""
    from django.urls import URLPattern, URLResolver, get_resolver
    from rest_framework.permissions import AllowAny

    from security.operation_registry import OPERATION_SPECS
    from security.permissions import HasErpOperation, IsAuthenticatedForERP

    errors = []
    mounted_ids = []
    public_routes = []

    def visit(patterns, prefix=""):
        for item in patterns:
            route = prefix + str(item.pattern)
            if isinstance(item, URLResolver):
                visit(item.url_patterns, route)
                continue
            if not isinstance(item, URLPattern):
                continue
            callback = item.callback
            view_class = getattr(callback, "cls", None)
            if view_class is None:
                errors.extend(_unclassified_api_callback_errors(route, view_class))
                continue
            permissions = tuple(getattr(view_class, "permission_classes", ()))
            operation_map = getattr(view_class, "erp_operation_specs", None)

            if AllowAny in permissions:
                public_routes.append(route)
                if operation_map:
                    errors.append(checks.Error(
                        f"Public route {route!r} must not carry ERP operation metadata.",
                        id=OPERATION_REGISTRY_CHECK_ID,
                    ))
                continue

            if IsAuthenticatedForERP not in permissions:
                if route.startswith("api/v1/"):
                    errors.append(checks.Error(
                        f"API route {route!r} has no IsAuthenticatedForERP first-party guard.",
                        id=OPERATION_REGISTRY_CHECK_ID,
                    ))
                continue

            if not permissions or permissions[0] is not IsAuthenticatedForERP:
                errors.append(checks.Error(
                    f"API route {route!r} must evaluate IsAuthenticatedForERP first.",
                    id=OPERATION_REGISTRY_CHECK_ID,
                ))
            if HasErpOperation not in permissions:
                errors.append(checks.Error(
                    f"Protected API route {route!r} has no HasErpOperation guard.",
                    id=OPERATION_REGISTRY_CHECK_ID,
                ))
                continue
            if not operation_map:
                errors.append(checks.Error(
                    f"Protected API route {route!r} has no operation declaration.",
                    id=OPERATION_REGISTRY_CHECK_ID,
                ))
                continue

            declared_handlers = {
                method.upper()
                for method in ("get", "post", "put", "patch", "delete")
                if method in view_class.__dict__
            }
            if "GET" in operation_map and "head" not in view_class.__dict__:
                errors.append(checks.Error(
                    f"GET route {route!r} must explicitly expose HEAD, which reuses its GET operation.",
                    id=OPERATION_REGISTRY_CHECK_ID,
                ))
            declared_methods = set(operation_map)
            if declared_methods != declared_handlers:
                errors.append(checks.Error(
                    f"Route {route!r} handler/declaration mismatch: "
                    f"handlers={sorted(declared_handlers)}, declarations={sorted(declared_methods)}.",
                    id=OPERATION_REGISTRY_CHECK_ID,
                ))
            for method, operation in operation_map.items():
                mounted_ids.append(operation.operation_id)

    try:
        visit(get_resolver().url_patterns)
    except Exception as exc:
        return [checks.Error(
            f"Could not inspect the mounted URL operation registry: {exc}",
            id=OPERATION_REGISTRY_CHECK_ID,
        )]

    errors.extend(_public_route_allowlist_errors(public_routes))

    if len(mounted_ids) != len(set(mounted_ids)):
        errors.append(checks.Error(
            "An operation ID is mounted more than once.",
            id=OPERATION_REGISTRY_CHECK_ID,
        ))
    registered_ids = set(OPERATION_SPECS)
    mounted_set = set(mounted_ids)
    if registered_ids != mounted_set:
        errors.append(checks.Error(
            "Operation registry/mounted URL mismatch: "
            f"unmounted={sorted(registered_ids - mounted_set)}, "
            f"unregistered={sorted(mounted_set - registered_ids)}.",
            id=OPERATION_REGISTRY_CHECK_ID,
        ))
    return errors


GM_SINGLETON_CHECK_ID = "security.E004"
GM_SLOT_MIGRATION_LABEL = ("security", "0005_gmroleslot")


def _gm_slot_table_exists(alias):
    from django.db import connections

    connection = connections[alias]
    table_names = set(connection.introspection.table_names())
    from security.models import GMRoleSlot

    return GMRoleSlot._meta.db_table in table_names


def _gm_slot_migration_applied(alias):
    """True when migration security.0005 is recorded on this alias."""
    from django.db import connections
    from django.db.migrations.recorder import MigrationRecorder

    connection = connections[alias]
    if "django_migrations" not in set(connection.introspection.table_names()):
        return False
    applied = MigrationRecorder(connection).applied_migrations()
    return GM_SLOT_MIGRATION_LABEL in applied


def _gm_singleton_errors_for_alias(alias):
    """E004 — singleton GM slot consistency for one database alias.

    Detects (finding codes from security.gm_slot, the single source of
    truth shared with the gm_slot_preflight command):
    - missing singleton GM slot row (migration security.0005 not applied);
    - invalid slot identity / duplicated slot rows;
    - a slot linking an assignment whose role is not the active GM role;
    - a slot linking a revoked assignment;
    - any non-closed GM assignment not represented by the singleton slot.

    A valid EMPTY slot on a fresh database with no GM provisioned is NOT an
    error: the system must be able to start safely before first-GM
    provisioning (zero active GM holders is an approved state). Messages
    carry row identifiers and counts only — never passwords, credentials,
    TOTP secrets, recovery material, or usernames.

    A database on which migration security.0005 is not yet applied is
    SKIPPED entirely — that is unmigrated state, not a post-migration
    inconsistency (the same rule the catalog drift check applies, §15.1).
    The pending migration owns the pre-migration reconciliation: it links a
    single non-closed GM candidate automatically and refuses multiple
    candidates with an actionable error, so the check must not pre-block
    it. After 0005 is applied, every finding below is enforced.
    """
    from django.db import router
    from security.gm_slot import inspect_slot_consistency
    from security.models import GMRoleSlot

    if not router.allow_migrate_model(alias, GMRoleSlot):
        return []
    # A pending migration is a normal pre-migration state. Once 0005 is
    # recorded, however, a missing slot table is corruption and must be
    # reported by inspect_slot_consistency() as security.E004.
    if not _gm_slot_migration_applied(alias):
        return []

    findings = inspect_slot_consistency(using=alias)
    return [
        checks.Error(
            f"Singleton GM slot state is inconsistent on database alias "
            f"{alias!r} ({code}): {message}. Run `python manage.py "
            f"gm_slot_preflight --database {alias}` for the read-only "
            f"report and reconcile manually; GM authority fails closed "
            f"until the state is consistent.",
            id=GM_SINGLETON_CHECK_ID,
        )
        for code, message in findings
    ]


def check_gm_singleton_slot_for_alias(alias):
    """Direct, deterministic entry point for the test suite."""
    return _gm_singleton_errors_for_alias(alias)


@register(Tags.database)
def check_gm_singleton_slot(app_configs=None, **kwargs):
    errors = []
    for alias in kwargs.get("databases") or []:
        errors.extend(_gm_singleton_errors_for_alias(alias))
    return errors
