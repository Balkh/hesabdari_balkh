# RBAC Foundation (W0-2A / R1) — Operational Notes

Scope: the dormant RBAC foundation implemented by the `security/w0-2a-r1-rbac-foundation` branch. The authoritative contract is `docs/architecture/W0-2A_RBAC_OFFLINE_SECURITY_DESIGN_DRAFT.md` (owner-approved at commit `e0d7db4505b7c04b1093c07e953aa4b1a3944f1d`); this page is an operator summary, not a policy document.

## What R1 installs

- **Six additive models** (`security.0002_rbac_models`): `Role`, `Permission`, `RolePermission`, `UserRoleAssignment`, `UserPermissionOverride`, `UserWarehouseScope`. Schema only; no view, permission, settings, middleware, or URL changes.
- **Canonical catalog and role seed** (`security.0003_seed_rbac_catalog`): 162 permission keys across 20 domains and the three system roles `GM` (152 grants), `ACCOUNTANT` (102), `WAREHOUSE_KEEPER` (12). Content comes exclusively from `backend/security/permissions_catalog.py`.
- **Legacy superuser mapping** (`security.0004_legacy_superuser_gm_mapping`): every existing `User` with `is_superuser=True` receives one active, indefinite `GM` role assignment, attributed to the system (`granted_by` NULL) with the marker reason `"W0-2A migration 0004: legacy superuser compatibility mapping (§24.2)"`. Non-superusers are never mapped; `is_staff` is never changed; `is_superuser=True` alone still confers no ERP authorization.
- **Dormant resolver** (`backend/security/authorization.py`): implements the approved fail-closed ten-step decision sequence. It is NOT wired into any view in R1 — no production code path calls it, and a structural test asserts no view module imports it.

## Determinism and drift protection

- The registry module validates itself on every seed and check run (`validate_catalog()`): exact counts (162 keys / 20 domains / scope 140-10-2-10 / statuses E11-S53-M88-R10 / 29 sensitive / seeds 152-102-12), key syntax `^[a-z][a-z_]+\.[a-z_]+\.[a-z_]+$`, no wildcards, and the ten `UNRESOLVED` keys (`documents.document.*` ×9 + `sales.document.approve`) never seeded to anyone.
- A database-tagged system check (`security.checks`, id `security.E001`) compares the seeded `security.Permission` rows against the registry during `migrate` (and `manage.py check --database <alias>`): missing rows, invented keys, or edited metadata fail loudly. The database catalog must never become an independent source of authorization truth.
- Seeding is `get_or_create`-based: re-running `migrate` (or the seed function) never duplicates rows and never overwrites operator-managed edits — divergence is reported by the drift check instead.

## Migration rollback behavior

- `security.0002` (schema) reverses normally: the six tables are dropped. Reversal on a database where user-specific authorization rows exist destroys only schema-plus-rows as any table drop does; take a backup first.
- `security.0003` (seed) reverse is a deliberate NO-OP: catalog rows are never deleted (§14.8). Rolling back past 0003 leaves the reference rows in place; re-applying converges to the same state because seeding is idempotent.
- `security.0004` reverse deletes exactly the migration-created rows: GM assignments with `granted_by` NULL, the marker reason, on superuser accounts. Operator-created assignments are untouched.

## Bootstrap interaction

The fresh-database bootstrap command exempts exactly the three RBAC reference models (`security.Role`, `security.Permission`, `security.RolePermission`) from its populated-data guard, at the same model-level granularity as the existing Django `contenttypes.ContentType` / `auth.Permission` exemptions (approved §24.5). The user-specific models `security.UserRoleAssignment`, `security.UserPermissionOverride`, and `security.UserWarehouseScope` are NOT exempt: any row in them blocks first-time bootstrap. See `docs/operations/FRESH_DATABASE_BOOTSTRAP.md`.

## Dormancy invariants (R1)

- No DRF view imports `security.authorization`; DRF default permission/authentication classes are unchanged (`IsAuthenticatedForERP`; Session + Basic).
- No endpoint enforcement, no Django Admin gate, no frontend authorization, no MFA/session/audit-chain artifacts — those belong to later approved batches (§24.2).
- The resolver denies everything it cannot positively prove: unexpected errors return `FAIL_CLOSED` (logged), unknown keys return `UNKNOWN_PERMISSION`, and scope failures return `SCOPE_DENIED`. There is no default-allow path.

## Verification summary (this branch)

Fresh and existing-database migrations, reverse/forward cycles, the full backend suite, and the catalog drift check were executed on SQLite (development) and PostgreSQL 16.4 (deployment engine). Exact commands, counts, and exit codes are recorded in the R1 owner handoff report accompanying this branch.
