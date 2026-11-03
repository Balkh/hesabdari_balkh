# W0-2B / R2 — Security Status and Reconciliation Addendum

**Date:** 2026-11-03  
**Repository:** `Balkh/hesabdari_balkh`  
**Main baseline:** `6498f37c3b37fd802676a11fd8012b98bad1c754`  
**Branch:** `security/w0-2b-r2-enforcement`  
**PR:** #57 — Draft / Open  
**State:** R2 API authorization is implemented on the branch and under exact-head verification. This is not a merge, production-enable, or freeze declaration.

## 1. Source-of-truth boundary

The approved W0-2A architecture remains on its separate design branch and is not merged by this addendum. Historical R1 decisions remain authoritative except where this R2 implementation explicitly adds a method-aware API declaration seam. R1 compatibility tests and accounting/domain contracts must remain unchanged.

The legacy key-only `resolve()` entry point remains available with its R1 evaluation behavior. Mounted R2 API views use `HasErpOperation` and `resolve_operation()`; both paths call the same `_resolve()` policy core. The R2 API entry point supplies server-owned per-method binding metadata. This avoids introducing a second authorization engine.

## 2. Live baseline and branch boundary

- `main` was re-fetched at `6498f37c3b37fd802676a11fd8012b98bad1c754`.
- PR #56 is merged at the baseline. PR #57 is a separate Draft PR; it is not merged.
- The branch `security/w0-2b-r2-enforcement` was created from that exact main SHA. All implementation commits are on this branch; `main` has not been changed.
- At latest verification, the PR base remains the baseline SHA and the PR head is the branch's latest commit.
- GitHub reports `main.protected=false` and no repository rulesets. Detailed classic branch-protection metadata was inaccessible through the current integration. Repository governance remains an owner-side action.
- The CI workflow in this branch uses `postgres:17.11`. The pre-existing workflow on `main` still uses PostgreSQL 16 until this PR is reviewed and merged.

## 3. Corrected mounted API inventory

At the pre-R2 baseline, the live URL configuration contained **13 URL patterns** and **15 HTTP handler methods**. R2 adds explicit `HEAD` handling to the four GET-capable protected routes. The branch therefore contains **13 URL patterns**, **19 HTTP handler methods**, **16 protected HTTP method handlers**, and **12 server-owned authorization operation specifications**. Each of the four `HEAD` handlers reuses the corresponding `GET` operation specification; it does not create a second permission key or a separate capability.

The three Core infrastructure operations remain explicit public `AllowAny` endpoints. The 12 R2 operation specifications use **11 distinct catalog permission keys**. The shared `purchases.landedcost.view` key is used by both collection-list and object-detail operations. `purchases.landedcost.delete_draft` remains catalog-only; no current route implements it. Django Admin is a separate surface and is not included in these API counts.

## 4. Implemented authorization contract

The R2 branch currently implements:

1. **Immutable operation declarations.** Each `OperationSpec` declares a stable operation ID, catalog permission key, COLLECTION or OBJECT binding, and server-owned target type/source. The registry and each view's method map are exposed as immutable mappings.
2. **Strict scope/declaration compatibility.** `OBJECT_REQUIRED` keys must be bound to the authenticated `SELF_USER`; `WAREHOUSE_REQUIRED` operations are rejected until their warehouse target binding is explicitly implemented; unresolved catalog keys cannot be executable operations.
3. **Authentication-first DRF permission.** `IsAuthenticatedForERP` remains first. The constructor-free `HasErpOperation` is second. No view method reaches its body before permission evaluation succeeds.
4. **Per-method permission selection.** Collection and object methods sharing the same catalog key can have different operation declarations. `HEAD` is mapped to `GET`; authenticated `OPTIONS` does not invoke a business method.
5. **Typed, server-derived targets.** Object PKs are read from the declared URL kwarg or authenticated `request.user`. The server-declared target kind chooses the model; a client cannot submit a model name or binding kind.
6. **GM target validation.** In the operation-aware path, a persisted object target is re-resolved and type-checked before a GM protected allow. The legacy R1 key-only GM behavior and R1 regression tests remain unchanged.
7. **Fail-closed behavior.** Missing declarations, incompatible bindings, missing targets, resolver exceptions, and a production configuration without an explicit authentication-only bypass all deny. Client responses do not expose internal scope-denial diagnostics.
8. **URL drift check.** `security.E003` checks mounted protected DRF API operations against the server-owned registry, verifies authentication-first ordering, rejects undeclared/mismatched methods and duplicate IDs, requires GET routes to expose the HEAD alias, and allows `AllowAny` only on the exact three approved Core routes.
9. **Production bypass boundary.** The base development/test profile explicitly opts into authenticated-only compatibility while R2 is being built. Production overrides `ERP_RBAC_ALLOW_AUTHENTICATED_ONLY=False`; therefore `ERP_RBAC_ENFORCEMENT=False` in Production does **not** become an authenticated-only allow. Protected API requests fail closed while enforcement remains disabled.

The branch does **not** currently persist permission-denial AuditEvents. The best-effort audit failure behavior below describes the required behavior if denial auditing is implemented after its control policy is settled; it is not a claim that denial auditing is already active.

## 5. Route inventory

| Method(s) | Route | Permission key | Operation ID | Binding |
|---|---|---|---|---|
| GET / HEAD | `/api/v1/security/me/` | `security.account.view_own` | `security.me.retrieve` | Object: authenticated self User |
| GET / HEAD | `/api/v1/fiscal-periods/` | `fiscal.period.view` | `fiscal.period.collection.list` | Collection |
| POST | `/api/v1/fiscal-periods/` | `fiscal.period.create` | `fiscal.period.collection.create` | Collection |
| POST | `/api/v1/fiscal-periods/<pk>/close/` | `fiscal.period.close` | `fiscal.period.object.close` | Object: FiscalPeriod |
| POST | `/api/v1/fiscal-periods/<pk>/reopen/` | `fiscal.period.reopen` | `fiscal.period.object.reopen` | Object: FiscalPeriod |
| POST | `/api/v1/fiscal-periods/<pk>/lock/` | `fiscal.period.lock` | `fiscal.period.object.lock` | Object: FiscalPeriod |
| POST | `/api/v1/fiscal-periods/<pk>/unlock/` | `fiscal.period.unlock` | `fiscal.period.object.unlock` | Object: FiscalPeriod |
| GET / HEAD | `/api/v1/purchases/landed-costs/` | `purchases.landedcost.view` | `purchases.landedcost.collection.list` | Collection |
| POST | `/api/v1/purchases/landed-costs/` | `purchases.landedcost.create` | `purchases.landedcost.collection.create` | Collection |
| GET / HEAD | `/api/v1/purchases/landed-costs/<pk>/` | `purchases.landedcost.view` | `purchases.landedcost.object.retrieve` | Object: LandedCostDocument |
| POST | `/api/v1/purchases/landed-costs/<pk>/post/` | `purchases.landedcost.post` | `purchases.landedcost.object.post` | Object: LandedCostDocument |
| POST | `/api/v1/purchases/landed-costs/<pk>/reverse/` | `purchases.landedcost.reverse` | `purchases.landedcost.object.reverse` | Object: LandedCostDocument |

Collection request-body identifiers such as landed-cost payee/currency IDs remain domain inputs validated by existing services; they are not authorization targets. No accounting, fiscal-period, landed-cost, or inventory service behavior was changed.

## 6. Verification evidence

### Completed exact-head CI runs

- **CI run #524**, SHA `5fbb46a12c257484cda7149a5c17e9eece94c40f`: all four jobs succeeded (Backend, PostgreSQL 17.11, Frontend, Tauri). Backend: **309 tests, 1 skipped**. PostgreSQL: **309 tests, no skips reported**. Django system checks reported no issues.
- **CI run #525**, SHA `87fda0f77c9cc28bf38807ec967e43bfadb9087b`: all four jobs succeeded. Backend: **311 tests, 1 skipped**. PostgreSQL 17.11: **311 tests, no skips reported**. This run includes the two negative tests for incompatible `OperationSpec` scope declarations.
- Earlier full CI run #522 at SHA `be50c64389403d324f86d2e66090fa377aecd1a2` also passed all four jobs with 308 tests on SQLite and PostgreSQL 17.11.
- The first R2 CI run failed on an incorrect test expectation that HEAD was automatically exposed. R2 explicitly added HEAD handlers and a follow-up passed. The initial failure is retained in CI history; the subsequent successful run is the relevant corrected evidence.

### Current candidate revision

The candidate at SHA `737ef5ad0ca1d745e741ef513ee388e0e88fe18d` adds an exact public-route allowlist to `security.E003`: only `api/v1/`, `api/v1/health/`, and `api/v1/health/missing/` may use `AllowAny`. Two tests cover the exact allowlist and prove that replacing one approved public route with a different route fails even when the total count remains three. CI run #527 is attached to that exact SHA and must complete successfully before the current candidate can be accepted. Do not infer test success from earlier SHA results.

No local container test was run in this session because the repository could not be cloned from the container network. Test evidence above is from GitHub Actions logs for the exact listed SHAs.

## 7. Remaining blockers — do not merge or enable Production

- **Django Admin GM gate is not implemented or activated.** The mounted `/admin/` currently retains Django's default AdminSite behavior. The approved design requires an active GM role in addition to `is_active` and `is_staff`, and explicitly forbids `is_superuser` as an authorization bypass.
- **GM provisioning is unresolved.** Migration `security.0004` maps only superusers that exist when that migration runs. A user created later through `createsuperuser` is not automatically assigned GM. No first-run local GM provisioning/recovery mechanism has been implemented here. Do not auto-assign GM to future superusers as a shortcut.
- **Account lockout is not effective yet.** `account_locked()` remains a no-op until W0-2D. The approved Admin contract also requires locked GM denial, so the final Admin gate depends on that capability or a separately reviewed equivalent.
- **Denial-audit flood policy is unresolved.** DRF throttles execute after permission checks and do not bound denied-request audit writes. No rate/threshold has been invented. `PERMISSION_DENIED` persistence, per-request deduplication, migration, and failure tests remain unimplemented until the owner-approved rate/control is defined.
- **Production enforcement is intentionally not enabled.** `ERP_RBAC_ENFORCEMENT` remains False by default. Production authenticated-only bypass is False, so protected API routes fail closed, but the explicit Production startup guard requiring enforcement=True has not been implemented. Do not deploy this candidate.
- **PostgreSQL 17.11 evidence exists for CI #524**, but the latest candidate SHA still needs its own completed run.
- **Repository protection remains owner-side.** GitHub reports `main.protected=false`; configure required checks and branch protection outside this implementation PR.
- **Credential rotation remains owner-side.** Any previously exposed GitHub tokens must be revoked by the owner. Do not reproduce token values in code, logs, reports, or chat; revocation is not verified until owner confirmation.

## 8. Implementation state and next sequence

| Batch | State |
|---|---|
| R2.0 documentation / baseline reconciliation | Implemented |
| R2.1 operation registry, immutable metadata, typed target resolver, shared policy path, system drift check | Implemented; latest two scope-validation tests pending exact-head CI |
| R2.2 GM-only Django Admin site and deployment activation | Blocked by GM provisioning, account inventory, and W0-2D lockout gap |
| R2.3 wiring the 12 current API operations and GET/HEAD behavior | Implemented; exact-head CI evidence recorded above |
| R2.4 authenticated denial AuditEvent and bounded audit flood policy | Blocked pending owner-defined control threshold |
| R2.5 Production startup guard requiring `ERP_RBAC_ENFORCEMENT=True` | Deferred until API/Admin/audit release gates are complete |
| R2.6 final dual-database verification, exact PR-head CI, user review and approval | In progress; no merge/freeze |

Do not claim PASS, VERIFIED, COMPLETE, GREEN, or FROZEN merely because code changes or a CI run exist. Report exact branch, commit SHA, test command/output, CI run, database version, skips, and outstanding caveats.

## 9. Frozen business invariants

R2 does not change accounting posting, immutable posted records, reversal-only history, inventory movement/costing, fiscal-period lifecycle services, landed-cost posting/reversal, idempotency, or any other business rule. Authorization wraps the existing API/services; it does not replace domain validation.

**Current status:** API authorization implementation is on Draft PR #57. The latest candidate requires exact-head CI completion and user review. No merge, production enablement, or freeze is authorized or implied.
